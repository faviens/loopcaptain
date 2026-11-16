"""The `loopcaptain` command: serve the board, check a folder, emit an event, run the MCP server."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from importlib.metadata import version as package_version
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from loopcaptain.agents import agent, agents, checkout_of, markdown
from loopcaptain.board.access import HOST
from loopcaptain.board.discover import (
    CONFIG_ENV,
    Config,
    as_written,
    config_in_use,
    config_target,
    edit_config,
    find_repos,
    load_config,
    survey,
)
from loopcaptain.protocol import spec_text, store
from loopcaptain.protocol.doctor import examine
from loopcaptain.protocol.models import EVENT_NAMES, AnyEvent, InboxEntry, Manifest, now
from loopcaptain.protocol.store import StoreError
from loopcaptain.protocol.validate import before_writing, validate_report

#: This repository's folder, for the MCP command a checkout prints; an installed package has none.
CHECKOUT = Path(__file__).resolve().parents[2]


def write_schemas(target: Path) -> list[Path]:
    """The protocol as JSON Schema, one file per file of a loop's folder."""
    target.mkdir(parents=True, exist_ok=True)
    schemas = {
        "loop.schema.json": Manifest.model_json_schema(),
        "event.schema.json": TypeAdapter(AnyEvent).json_schema(),
        "inbox.schema.json": InboxEntry.model_json_schema(),
    }
    written = []
    for name, schema in schemas.items():
        path = target / name
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    return written


#: What a `key=value` of `emit` may parse to and still have been meant as text: `commit=1234567`.
SCALARS = (bool, int, float, type(None))


def emit(repo: Path, loop_id: str, event: str, fields: list[str]) -> list[str]:
    """Append one event from `key=value` pairs; what it returns are warnings, the line is written.

    A value that parses as JSON is taken as JSON (`round=2`, `blocks=true`, `ids=["a"]`). Where the
    event wants text and the value parsed as a number, true, false or null, it is taken as written:
    a commit id of digits, a summary of "42".
    """
    written: dict[str, str] = {}
    for pair in fields:
        key, sep, raw = pair.partition("=")
        if not sep:
            raise StoreError(f"{pair!r}: expected key=value")
        written[key] = raw
    stamp: dict[str, object] = {"ts": now().isoformat(), "event": event}
    data = {**{key: as_json(raw) for key, raw in written.items()}, **stamp}
    try:
        parsed = store.parse_event(data)
    except ValidationError as error:
        refused = {str(item["loc"][1]) for item in error.errors() if len(item["loc"]) > 1}
        as_text = {key: written[key] for key in refused & set(written) if isinstance(data[key], SCALARS)}
        if not as_text:
            raise StoreError(store.short_error(error)) from error
        try:
            parsed = store.parse_event({**data, **as_text})
        except ValidationError:
            raise StoreError(store.short_error(error)) from error
    report = before_writing(repo, loop_id, parsed)
    if report.problems:
        raise StoreError(f"not recorded: {'; '.join(report.problems)}")
    store.append_event(repo, loop_id, parsed)
    return report.warnings


def as_json(raw: str) -> object:
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        return raw


def serve_command() -> str:
    """How the board is started from here: the Makefile's target in a checkout, the command when installed."""
    return "make serve" if checkout_of(CHECKOUT) and Path("Makefile").is_file() else "loopcaptain serve"


def watched_line() -> str:
    """How many repositories the board will show and which config file says so, in a few words."""
    try:
        config = load_config()
        count = len(find_repos(config))
    except StoreError as error:
        return f"the config cannot be read ({error}); the board's first page says the same"
    source = as_written(config.source) if config.source else "no config file"
    noun = "repository" if count == 1 else "repositories"
    return f"{count} {noun} with loops, config: {source}"


def other_config_warnings() -> list[str]:
    """A warning where a board started in this folder reads another config than `watch` writes."""
    written = config_target()
    try:
        read = config_in_use()
    except StoreError as error:
        return [f"warning: {error}"]
    if read is None or read.resolve() == written.resolve():
        return []
    return [
        f"warning: a board started in this folder reads {as_written(read)}, not {as_written(written)}; "
        f"set {CONFIG_ENV} to the one you mean, or edit that file"
    ]


def watch_warnings(path: Path, *, root: bool) -> list[str]:
    """What `watch` says beyond what it wrote: a folder that shows nothing yet, a config nobody reads."""
    config = Config(roots=(path.resolve(),)) if root else Config(repos=(path.resolve(),))
    found, unreadable = survey(config)
    lines = [f"warning: {as_written(item.path)} cannot be read: {item.message}" for item in unreadable]
    if not found and not unreadable:
        where = "no sub-folder of it has" if root else "it has no"
        lines.append(
            f"warning: {where} `.loops/` folder with a loop yet; the board shows it once a loop is registered"
        )
    return lines + other_config_warnings()


def unwatched_warnings(target: Path) -> list[str]:
    """After `demo --no-watch`: say so where the board started here would not show the example."""
    try:
        config = load_config()
    except StoreError as error:
        return [f"warning: {error}"]
    listed = target.resolve() in config.repos or target.resolve().parent in config.roots
    if config.source is None or listed:
        return []
    return [
        f"warning: a board started in this folder reads {as_written(config.source)}, which does not list "
        f"{as_written(target)}; `loopcaptain watch {target}` adds it"
    ]


def port_is_free(port: int) -> bool:
    """Whether the board can listen on this port of 127.0.0.1, asked before anything is printed."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((HOST, port))
        except (OSError, OverflowError):
            return False
    return True


def serve_board(port: int) -> int:
    """Say where the board is, then serve it until it is stopped."""
    from loopcaptain.board.app import entry_address, serve, session_for

    if not port_is_free(port):
        raise StoreError(
            f"port {port} on {HOST} cannot be used: another board or program has it, or it is no port. "
            f"Stop that one, or pick another: `loopcaptain serve --port <number>`"
        )
    session = session_for(port)
    sys.stdout.write(f"open {entry_address(port, session)}   ({watched_line()})\n")
    sys.stdout.flush()
    serve(port, session)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="loopcaptain", description="One board for every agent loop.")
    parser.add_argument(
        "--version", action="version", version=f"loopcaptain {package_version('loopcaptain')}"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="the board on 127.0.0.1")
    serve.add_argument("--port", type=int, default=8484, help="the port on 127.0.0.1, default 8484")

    validate = commands.add_parser("validate", help="check a repository's .loops folders")
    validate.add_argument("repo", type=Path)
    validate.add_argument("--strict", action="store_true", help="count warnings as problems")

    emit_cmd = commands.add_parser(
        "emit", help="append one event: loopcaptain emit <loop> <event> key=value ..."
    )
    emit_cmd.add_argument("loop")
    emit_cmd.add_argument("event", choices=EVENT_NAMES)
    emit_cmd.add_argument(
        "fields",
        nargs="*",
        help="key=value; a value is read as JSON where it parses (round=2, blocks=true, "
        "ids='[\"a\"]'), and as text where the field is text (commit=1234567)",
    )
    emit_cmd.add_argument("--repo", type=Path, default=Path("."))

    schema = commands.add_parser("schema", help="write the protocol as JSON Schema")
    schema.add_argument("target", type=Path)

    doctor = commands.add_parser("doctor", help="send a loop a stop and check that it takes it and ends")
    doctor.add_argument("repo", type=Path)
    doctor.add_argument("loop")
    doctor.add_argument("--timeout", type=float, default=600, help="seconds to wait, default 600")

    watch = commands.add_parser(
        "watch", help="add a repository, or with --root a folder of them, to the board"
    )
    watch.add_argument("path", type=Path)
    watch.add_argument("--root", action="store_true", help="every sub-folder with .loops/ is a repository")
    unwatch = commands.add_parser("unwatch", help="take a folder off the board")
    unwatch.add_argument("path", type=Path)

    demo = commands.add_parser(
        "demo", help="write the example loop into a folder and watch it; costs nothing"
    )
    demo.add_argument("--target", type=Path, default=Path("~/.local/share/loopcaptain/demo"))
    demo.add_argument("--no-watch", action="store_true", help="write it, but leave the config alone")

    mcp_config = commands.add_parser("mcp-config", help="how one coding agent adds the MCP server")
    mcp_config.add_argument("agent", nargs="?", default="", help="claude-code, codex, gemini, cursor, ...")
    mcp_config.add_argument(
        "--checkout", default=checkout_of(CHECKOUT), help="the folder of this repository, if run from one"
    )
    mcp_config.add_argument("--markdown", action="store_true", help="print the page for every agent")

    commands.add_parser("spec", help="print LOOPS.md, the protocol to paste into a loop")
    commands.add_parser("mcp", help="run the MCP server on stdio")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except StoreError as error:
        sys.stderr.write(f"loopcaptain: {error}\n")
        return 1


def run(args: argparse.Namespace) -> int:
    if args.command == "validate":
        report = validate_report(args.repo.expanduser().resolve())
        problems = report.problems + (report.warnings if args.strict else [])
        warnings = [] if args.strict else report.warnings
        for line in problems:
            sys.stdout.write(f"problem: {line}\n")
        for line in warnings:
            sys.stdout.write(f"warning: {line}\n")
        if problems:
            sys.stdout.write(f"{len(problems)} problem(s), {len(warnings)} warning(s)\n")
        else:
            sys.stdout.write(f"ok, {len(warnings)} warning(s)\n" if warnings else "ok\n")
        return 1 if problems else 0
    if args.command == "emit":
        for line in emit(args.repo.expanduser().resolve(), args.loop, args.event, args.fields):
            sys.stderr.write(f"warning: {line}\n")
        return 0
    if args.command == "schema":
        for path in write_schemas(args.target):
            sys.stdout.write(f"{path}\n")
        return 0
    if args.command == "doctor":
        sys.stdout.write("waiting for the loop to take a stop; start it now if it is not running\n")
        checkup = examine(args.repo.expanduser().resolve(), args.loop, args.timeout)
        sys.stdout.write("".join(f"{line}\n" for line in checkup.lines()))
        return 0 if checkup.passed else 1
    if args.command in ("watch", "unwatch"):
        entry = as_written(args.path)
        if args.command == "watch":
            if not args.path.expanduser().is_dir():
                raise StoreError(f"{args.path} is not a folder; nothing was written")
            changes = edit_config(args.path, add=("roots" if args.root else "repos", entry))
            changes += watch_warnings(args.path.expanduser(), root=args.root)
        else:
            changes = edit_config(args.path, remove=entry)
        sys.stdout.write("".join(f"{line}\n" for line in changes))
        return 0
    if args.command == "demo":
        from loopcaptain.demo import DemoError, write_demo

        target = args.target.expanduser()
        try:
            write_demo(target)
        except DemoError as error:
            raise StoreError(str(error)) from error
        sys.stdout.write(f"the example loop is in {target}\n")
        if args.no_watch:
            lines = unwatched_warnings(target)
        else:
            lines = edit_config(target, add=("repos", as_written(target))) + other_config_warnings()
        sys.stdout.write("".join(f"{line}\n" for line in lines))
        sys.stdout.write(f"start the board with `{serve_command()}` and open the address it prints\n")
        return 0
    if args.command == "mcp-config":
        if args.markdown:
            sys.stdout.write(markdown())
            return 0
        if not args.agent:
            sys.stdout.write("".join(f"{item.key:12} {item.name}\n" for item in agents(args.checkout)))
            return 0
        try:
            item = agent(args.agent, args.checkout)
        except KeyError as error:
            raise StoreError(str(error.args[0])) from error
        sys.stdout.write(f"{item.name}\n\n{item.add}\n\nunattended: {item.headless}\n")
        return 0
    if args.command == "spec":
        sys.stdout.write(spec_text())
        return 0
    if args.command == "mcp":
        from loopcaptain.mcp_server.server import serve_stdio

        serve_stdio()
        return 0
    return serve_board(args.port)


if __name__ == "__main__":
    raise SystemExit(main())
