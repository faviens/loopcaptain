"""The `loopcaptain` command: serve the board, check a folder, emit an event, run the MCP server."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from collections.abc import Callable
from dataclasses import replace
from importlib.metadata import version as package_version
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from loopcaptain.agents import agent, agents, checkout_of, markdown
from loopcaptain.board.access import HOST
from loopcaptain.board.discover import (
    CONFIG_ENV,
    Config,
    LoopView,
    as_written,
    config_in_use,
    config_target,
    edit_config,
    find_repos,
    load_all,
    load_config,
    put_aside,
    survey,
)
from loopcaptain.board.filters import ago
from loopcaptain.board.overview import GROUPS, group_of
from loopcaptain.protocol import spec_text, store
from loopcaptain.protocol.doctor import examine
from loopcaptain.protocol.models import EVENT_NAMES, FOLDER, AnyEvent, InboxEntry, Manifest, now
from loopcaptain.protocol.signing import board_keys
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


#: The folder uv keeps the temporary environments of `uvx` in, one sub-folder each.
UVX_CACHE_PREFIX = "archive-v"


def run_through_uvx() -> bool:
    """Whether this process came from `uvx`: uv started it, from an environment in uv's cache.

    `uvx` puts its environment's `bin` on `PATH` for this process only, so `PATH` cannot tell."""
    return "UV" in os.environ and Path(sys.prefix).parent.name.startswith(UVX_CACHE_PREFIX)


def serve_command() -> str:
    """How the board is started from here: the Makefile's target in a checkout, `uvx` when this came
    from `uvx`, else the installed command."""
    if checkout_of(CHECKOUT) and Path("Makefile").is_file():
        return "make serve"
    return "uvx loopcaptain serve" if run_through_uvx() else "loopcaptain serve"


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
    # The keys exist before the first answer, so a loop can tell the board's lines from the start.
    board_keys()
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
    validate.add_argument("repo", type=Path, help="the repository whose .loops folders are checked")
    validate.add_argument("--strict", action="store_true", help="count warnings as problems")

    emit_cmd = commands.add_parser(
        "emit", help="append one event to a loop's log, its fields as key=value pairs, for a loop in shell"
    )
    emit_cmd.add_argument("loop", help="the loop's id, the name of its folder in .loops/")
    emit_cmd.add_argument(
        "event",
        choices=EVENT_NAMES,
        help=f"the event to append, one of: {', '.join(EVENT_NAMES)}",
        metavar="event",
    )
    emit_cmd.add_argument(
        "fields",
        nargs="*",
        help="key=value; a value is read as JSON where it parses (round=2, blocks=true, "
        "ids='[\"a\"]'), and as text where the field is text (commit=1234567)",
    )
    emit_cmd.add_argument(
        "--repo", type=Path, default=Path("."), help="the repository the loop lives in, default: this folder"
    )

    schema = commands.add_parser("schema", help="write the protocol as JSON Schema")
    schema.add_argument("target", type=Path, help="the folder the schema files are written into")

    doctor = commands.add_parser("doctor", help="send a loop a stop and check that it takes it and ends")
    doctor.add_argument("repo", type=Path, help="the repository the loop lives in")
    doctor.add_argument("loop", help="the loop's id, the name of its folder in .loops/")
    doctor.add_argument("--timeout", type=float, default=600, help="seconds to wait, default 600")

    watch = commands.add_parser(
        "watch", help="add a repository, or with --root a folder of them, to the board"
    )
    watch.add_argument("path", type=Path, help="a repository, or with --root a folder of repositories")
    watch.add_argument("--root", action="store_true", help="every sub-folder with .loops/ is a repository")
    unwatch = commands.add_parser("unwatch", help="take a folder off the board")
    unwatch.add_argument("path", type=Path, help="the folder to take off, however the config spells it")
    status = commands.add_parser("status", help="where every watched loop stands, in a terminal")
    status.add_argument("--all", action="store_true", help="hidden and finished loops too")
    inbox = commands.add_parser(
        "inbox", help="what the person sent a loop since the last call, one line each, for a loop in shell"
    )
    inbox.add_argument("loop", help="the loop's id, the name of its folder in .loops/")
    inbox.add_argument(
        "--repo", type=Path, default=Path("."), help="the repository the loop lives in, default: this folder"
    )
    inbox.add_argument(
        "--json", action="store_true", help="every entry as a JSON line, with signed and stale"
    )
    for name, about in (
        ("hide", "take one loop off the board's first page and out of its figures"),
        ("unhide", "show a hidden loop on the first page again"),
    ):
        one_loop = commands.add_parser(name, help=about)
        one_loop.add_argument("repo", type=Path, help="the repository the loop lives in")
        one_loop.add_argument("loop", help="the loop's id, the name of its folder in .loops/")

    demo = commands.add_parser(
        "demo", help="write the example loop into a folder and watch it; costs nothing"
    )
    demo.add_argument(
        "--target",
        type=Path,
        default=Path("~/.local/share/loopcaptain/demo"),
        help="the folder the example loop is written into, default ~/.local/share/loopcaptain/demo",
    )
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
        return COMMANDS[args.command](args)
    except StoreError as error:
        sys.stderr.write(f"loopcaptain: {error}\n")
    except OSError as error:
        # A folder that cannot be written, a file that is not there: one line, not a traceback.
        named = f"{error.filename}: " if error.filename else ""
        sys.stderr.write(f"loopcaptain: {named}{error.strerror or error}\n")
    return 1


def say(lines: list[str]) -> None:
    sys.stdout.write("".join(f"{line}\n" for line in lines))


def run_validate(args: argparse.Namespace) -> int:
    report = validate_report(args.repo.expanduser().resolve())
    problems = report.problems + (report.warnings if args.strict else [])
    warnings = [] if args.strict else report.warnings
    say([f"problem: {line}" for line in problems] + [f"warning: {line}" for line in warnings])
    if problems:
        say([f"{len(problems)} problem(s), {len(warnings)} warning(s)"])
    else:
        say([f"ok, {len(warnings)} warning(s)" if warnings else "ok"])
    return 1 if problems else 0


def run_emit(args: argparse.Namespace) -> int:
    for line in emit(args.repo.expanduser().resolve(), args.loop, args.event, args.fields):
        sys.stderr.write(f"warning: {line}\n")
    return 0


def run_schema(args: argparse.Namespace) -> int:
    say([str(path) for path in write_schemas(args.target)])
    return 0


def run_doctor(args: argparse.Namespace) -> int:
    say(["waiting for the loop to take a stop; start it now if it is not running"])
    checkup = examine(args.repo.expanduser().resolve(), args.loop, args.timeout)
    say(checkup.lines())
    return 0 if checkup.passed else 1


def run_watch(args: argparse.Namespace) -> int:
    if not args.path.expanduser().is_dir():
        raise StoreError(f"{args.path} is not a folder; nothing was written")
    changes = edit_config(args.path, add=("roots" if args.root else "repos", as_written(args.path)))
    say(changes + watch_warnings(args.path.expanduser(), root=args.root))
    return 0


def run_unwatch(args: argparse.Namespace) -> int:
    say(edit_config(args.path, remove=as_written(args.path)))
    return 0


def loop_folder(args: argparse.Namespace) -> Path:
    """The folder of the loop a command names; the loop must be there, so a typo hides nothing."""
    repo = args.repo.expanduser().resolve()
    if args.loop not in store.loop_ids(repo):
        raise StoreError(f"no loop {args.loop!r} in {args.repo}; nothing was written")
    return store.loop_dir(repo, args.loop)


def run_hide(args: argparse.Namespace) -> int:
    folder = loop_folder(args)
    say(edit_config(folder, add=("hidden", as_written(folder))) + other_config_warnings())
    return 0


def run_unhide(args: argparse.Namespace) -> int:
    folder = (
        args.repo.expanduser().resolve() / FOLDER / args.loop
    )  # a loop that is gone can still be unhidden
    say(edit_config(folder, remove=as_written(folder)))
    return 0


def status_lines(views: list[LoopView], *, everything: bool) -> list[str]:
    """One line per loop, what needs the person first: status, where, round, last line, what it asks."""
    order = list(GROUPS)
    kept = [view for view in views if everything or group_of(view) not in ("hidden", "finished")]
    kept.sort(key=lambda view: (order.index(group_of(view)), view.repo.key, view.loop_id))
    width = max((len(f"{view.repo.key}/{view.loop_id}") for view in kept), default=0)
    lines = []
    for view in kept:
        state, name = view.state, f"{view.repo.key}/{view.loop_id}"
        if state is None:
            lines.append(f"{'unreadable':10}  {name:{width}}  {view.error}")
            continue
        last = state.last_round
        told = f"asks: {state.question.text}" if state.question else state.last_line
        parts = [
            f"round {last.number}" if last else "no round",
            ago(state.last_event),
            " ".join(told.split()),
        ]
        lines.append(f"{state.status:10}  {name:{width}}  " + "  ".join(part for part in parts if part))
    return lines


def run_status(args: argparse.Namespace) -> int:
    config = load_config()
    views = [replace(view, hidden=put_aside(config, view.repo, view.loop_id)) for view in load_all(config)]
    lines = status_lines(views, everything=args.all)
    waiting = sum(1 for view in views if not view.hidden and view.state and view.state.question)
    left_out = len(views) - len(lines)
    say(lines or ["no loop to show"])
    say(
        [
            f"{waiting} waiting for you"
            + (f", {left_out} hidden or finished not shown (--all)" if left_out else "")
        ]
    )
    return 0


def run_inbox(args: argparse.Namespace) -> int:
    """The loop's side of the inbox for a loop that is no Python: what the person sent, marked read.

    Without `--json` only what a loop may act on is printed, `kind`, a tab, the text on one line:
    entries the board signed for this loop that answer the present asking. The rest is counted
    on standard error, so a script that reads the lines cannot take a forged one by mistake."""
    repo = args.repo.expanduser().resolve()
    if args.loop not in store.loop_ids(repo):
        raise StoreError(f"no loop {args.loop!r} in {args.repo}")
    entries = store.taken(repo, args.loop)
    if args.json:
        say([json.dumps(entry, ensure_ascii=False) for entry in entries])
        return 0
    good = [entry for entry in entries if entry["signed"] is True and not entry["stale"]]
    say([f"{entry['kind']}\t{' '.join(str(entry.get('text', '')).split())}" for entry in good])
    if len(good) < len(entries):
        unchecked = any(entry["signed"] is None for entry in entries)
        why = (
            "this loop's key cannot be read, so nothing was checked"
            if unchecked
            else "not from the board, or stale"
        )
        sys.stderr.write(
            f"loopcaptain: {len(entries) - len(good)} entry(ies) left out: {why}; --json shows them\n"
        )
    return 0


def run_demo(args: argparse.Namespace) -> int:
    from loopcaptain.demo import DemoError, write_demo

    target = args.target.expanduser()
    try:
        write_demo(target)
    except DemoError as error:
        raise StoreError(str(error)) from error
    say([f"the example loop is in {target}"])
    if args.no_watch:
        say(unwatched_warnings(target))
    else:
        say(edit_config(target, add=("repos", as_written(target))) + other_config_warnings())
    say([f"start the board with `{serve_command()}` and open the address it prints"])
    return 0


#: How the MCP server gets its SDK, said wherever it is missing or about to be needed.
MCP_EXTRA = "Install with it: `uv tool install 'loopcaptain[mcp]'` (or `pipx install 'loopcaptain[mcp]'`)"


def run_mcp_config(args: argparse.Namespace) -> int:
    if args.markdown:
        sys.stdout.write(markdown())
        return 0
    if not args.agent:
        say([f"{item.key:12} {item.name}" for item in agents(args.checkout)])
        return 0
    try:
        item = agent(args.agent, args.checkout)
    except KeyError as error:
        raise StoreError(str(error.args[0])) from error
    sys.stdout.write(f"{item.name}\n\n{item.add}\n\nunattended: {item.headless}\n")
    if not args.checkout:
        sys.stdout.write(f"\nthe server needs the MCP extra. {MCP_EXTRA}\n")
    return 0


def run_spec(args: argparse.Namespace) -> int:
    sys.stdout.write(spec_text())
    return 0


def run_mcp(args: argparse.Namespace) -> int:
    try:
        from loopcaptain.mcp_server.server import serve_stdio
    except ImportError as error:
        if (error.name or "").split(".")[0] != "mcp":
            raise
        raise StoreError(f"the MCP server needs the extra, which is not installed. {MCP_EXTRA}") from error

    serve_stdio()
    return 0


def run_serve(args: argparse.Namespace) -> int:
    return serve_board(args.port)


#: One function per command the parser knows.
COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "serve": run_serve,
    "validate": run_validate,
    "emit": run_emit,
    "schema": run_schema,
    "doctor": run_doctor,
    "watch": run_watch,
    "unwatch": run_unwatch,
    "status": run_status,
    "inbox": run_inbox,
    "hide": run_hide,
    "unhide": run_unhide,
    "demo": run_demo,
    "mcp-config": run_mcp_config,
    "spec": run_spec,
    "mcp": run_mcp,
}


if __name__ == "__main__":
    raise SystemExit(main())
