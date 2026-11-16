"""Write the documentation pages that come from the code: `make docs-pages`.

The command line from its argument parser, the MCP tools from the server, the agents from
`loopcaptain.agents`, and `llms.txt`. A test fails when a committed page differs from what this
writes, so the reference cannot drift from the code.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import sys
import tomllib
from pathlib import Path

from loopcaptain import agents
from loopcaptain.cli import build_parser
from loopcaptain.mcp_server import server

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
GENERATED = "<!-- Written by scripts/docs_pages.py from the code: `make docs-pages`. Do not edit. -->"


def cli_page() -> str:
    parser = build_parser()
    lines = [
        GENERATED,
        "",
        "# The command line",
        "",
        "`loopcaptain <command>`; from a checkout, `uv run loopcaptain <command>`.",
        "",
    ]
    subparsers = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    helps = {choice.dest: choice.help for choice in subparsers._choices_actions}
    for name, sub in subparsers.choices.items():
        lines += [f"## `{name}`", "", f"{(helps.get(name) or '').capitalize()}.", ""]
        usage = sub.format_usage().replace("usage: ", "").strip()
        lines += ["```text", usage, "```", ""]
        options = [action for action in sub._actions if not isinstance(action, argparse._HelpAction)]
        if options:
            lines += ["| Argument | Meaning |", "|---|---|"]
            for action in options:
                flag = ", ".join(action.option_strings) or action.dest
                lines.append(f"| `{flag}` | {action.help or ''} |")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def mcp_page() -> str:
    tools = asyncio.run(server.server.list_tools())
    lines = [GENERATED, "", "# The MCP tools", "", server.__doc__.strip() if server.__doc__ else "", ""]
    for tool in tools:
        function = getattr(server, tool.name)
        doc = inspect.cleandoc(function.__doc__ or "")
        signature = str(inspect.signature(function)).replace("'", "")
        lines += [f"## `{tool.name}`", "", "```text", f"{tool.name}{signature}", "```", "", doc, ""]
    return "\n".join(lines).rstrip() + "\n"


def addresses() -> tuple[str, str]:
    """Where the documentation site and the repository's files on its main branch are read."""
    urls = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["urls"]
    return urls["Documentation"].rstrip("/"), urls["Repository"].rstrip("/") + "/blob/main"


def llms_txt() -> str:
    """The index for a model. Every address is absolute: the file is read from the site and from the
    repository, and a relative path leads somewhere in only one of them."""
    prompts = ROOT / "standard" / "prompts"
    site, files = addresses()
    return "\n".join(
        [
            "# Loopcaptain",
            "",
            "> An open protocol for agent loops and a local dashboard to monitor and steer them. A loop",
            "> (a script, a Ralph loop, a long-running agent session) writes a few small files into",
            "> .loops/<loop-id>/ in its own repository: loop.json, events.jsonl, inbox.jsonl. The board",
            "> shows where each loop stands, what it cost and what waits for a person, and writes the",
            "> person's answer, note or stop back. No dependency, no cloud, nothing leaves the machine.",
            "",
            "## Start",
            "",
            f"- [Build a loop]({files}/standard/prompts/build-a-loop.md): "
            + (prompts / "build-a-loop.md").read_text().splitlines()[0],
            f"- [Watch the loops on this machine]({files}/standard/prompts/watch-my-loops.md): "
            + (prompts / "watch-my-loops.md").read_text().splitlines()[0],
            f"- [Installation]({site}/installation/): `uv tool install loopcaptain`, from PyPI; Python 3.12 or later",
            f"- [Get started]({site}/get-started/): the example loop, free, in five minutes",
            f"- [Setup]({site}/setup/): what the board watches, checking a loop, when a loop does not show",
            "",
            "## The standard",
            "",
            f"- [LOOPS.md]({files}/standard/LOOPS.md): the protocol, the helper to paste, conformance",
            f"- [AGENTS.md for a loop]({files}/standard/AGENTS.md): connect a loop, or build one from nothing",
            f"- [Works with every agent]({site}/agents/): how each coding agent adds the MCP server",
            "",
            "## Optional",
            "",
            f"- [The command line]({site}/reference/cli/)",
            f"- [The MCP tools]({site}/reference/mcp/)",
            f"- [Security]({site}/security/)",
            "",
        ]
    )


def pages() -> dict[Path, str]:
    return {
        DOCS / "reference" / "cli.md": cli_page(),
        DOCS / "reference" / "mcp.md": mcp_page(),
        DOCS / "agents.md": agents.markdown(),
        DOCS / "llms.txt": llms_txt(),
    }


def main() -> int:
    for path, text in pages().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        sys.stdout.write(f"{path.relative_to(ROOT)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
