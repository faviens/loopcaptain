"""The `loopcaptain` command: serve the board, check a folder, emit an event, run the MCP server."""

from __future__ import annotations

import argparse
import json
import sys
from importlib.metadata import version as package_version
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from loopcaptain.agents import agent, agents, checkout_of, markdown
from loopcaptain.board.discover import as_written, edit_config
from loopcaptain.protocol import spec_text, store
from loopcaptain.protocol.doctor import examine
from loopcaptain.protocol.models import EVENT_NAMES, AnyEvent, InboxEntry, Manifest, now
from loopcaptain.protocol.store import StoreError
from loopcaptain.protocol.validate import validate_report

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


def emit(repo: Path, loop_id: str, event: str, fields: list[str]) -> None:
    """Append one event from `key=value` pairs; a value that parses as JSON is taken as JSON."""
    data: dict[str, object] = {"ts": now().isoformat(), "event": event}
    for pair in fields:
        key, sep, raw = pair.partition("=")
        if not sep:
            raise StoreError(f"{pair!r}: expected key=value")
        try:
            data[key] = json.loads(raw)
        except json.JSONDecodeError:
            data[key] = raw
    try:
        parsed = store.parse_event(data)
    except ValidationError as error:
        raise StoreError(store.short_error(error)) from error
    store.read_manifest(repo, loop_id)
    store.append_event(repo, loop_id, parsed)


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
    emit_cmd.add_argument("fields", nargs="*")
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
        emit(args.repo.expanduser().resolve(), args.loop, args.event, args.fields)
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
                raise StoreError(f"{args.path} is not a folder")
            changes = edit_config(args.path, add=("roots" if args.root else "repos", entry))
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
        if not args.no_watch:
            sys.stdout.write(
                "".join(f"{line}\n" for line in edit_config(target, add=("repos", as_written(target))))
            )
        sys.stdout.write("start the board with `loopcaptain serve` and open http://127.0.0.1:8484\n")
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
    from loopcaptain.board.app import serve

    serve(args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
