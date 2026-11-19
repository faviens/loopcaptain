"""How each coding agent adds the Loopcaptain MCP server and runs a loop without a person at the keyboard.

One source for the command line (`loopcaptain mcp-config <agent>`), the board's Connect page and the
"Works with every agent" page (`docs/agents.md`, written by `make docs-pages`). Each entry was taken from
that agent's own documentation on the date in CHECKED.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CHECKED = "2026-11-15"
#: The MCP server as a command and its arguments, run from a checkout; `{checkout}` is its folder.
SERVER = ("uv", "run", "--project", "{checkout}", "loopcaptain", "mcp")
#: The same, where the package is installed.
INSTALLED_SERVER = ("loopcaptain", "mcp")
#: Other names a person types for an agent, and the key each means.
ALIASES = {"claude": "claude-code"}


def checkout_of(folder: Path) -> str:
    """The folder of this repository if the code runs from a checkout of it, else "" (installed)."""
    return str(folder) if (folder / "pyproject.toml").is_file() and (folder / "standard").is_dir() else ""


@dataclass(frozen=True)
class Agent:
    key: str
    name: str
    reads: str  # the instruction files it loads by itself
    add: str  # how to add the server: a command, or the file and block
    headless: str  # the command to put in commands.start for an unattended loop


def server_argv(checkout: str) -> list[str]:
    if not checkout:
        return list(INSTALLED_SERVER)
    return [part.format(checkout=checkout) for part in SERVER]


def mcp_servers_json(checkout: str, top: str = "mcpServers", stdio_type: bool = False) -> str:
    argv = server_argv(checkout)
    entry: dict[str, object] = {"command": argv[0], "args": argv[1:]}
    if stdio_type:
        entry = {"type": "stdio", **entry}
    return json.dumps({top: {"loopcaptain": entry}}, indent=2)


def agents(checkout: str) -> list[Agent]:
    command = " ".join(server_argv(checkout))
    argv = server_argv(checkout)
    opencode = json.dumps(
        {"mcp": {"loopcaptain": {"type": "local", "command": argv, "enabled": True}}}, indent=2
    )
    codex_toml = f'[mcp_servers.loopcaptain]\ncommand = "{argv[0]}"\nargs = {json.dumps(argv[1:])}'
    return [
        Agent(
            "claude-code",
            "Claude Code",
            "`CLAUDE.md` (import `AGENTS.md` with a line `@AGENTS.md`)",
            f"claude mcp add loopcaptain -- {command}",
            'claude -p "Run one round of the loop as AGENTS.md says" --output-format json',
        ),
        Agent(
            "codex",
            "Codex CLI",
            "`AGENTS.md`",
            f"codex mcp add loopcaptain -- {command}\n\n# or in ~/.codex/config.toml:\n{codex_toml}",
            'codex exec --json "Run one round of the loop as AGENTS.md says"',
        ),
        Agent(
            "gemini",
            "Gemini CLI",
            "`GEMINI.md` (import `AGENTS.md` with a line `@AGENTS.md`)",
            f"gemini mcp add loopcaptain {command}\n\n"
            f"# or in .gemini/settings.json:\n{mcp_servers_json(checkout)}",
            'gemini -p "Run one round of the loop as AGENTS.md says" --output-format json',
        ),
        Agent(
            "cursor",
            "Cursor",
            "`AGENTS.md`, `.cursor/rules/`",
            f"# .cursor/mcp.json\n{mcp_servers_json(checkout)}",
            'cursor-agent -p "Run one round of the loop as AGENTS.md says" --output-format json',
        ),
        Agent(
            "vscode",
            "VS Code (Copilot agent mode)",
            "`AGENTS.md`, `.github/copilot-instructions.md`",
            f"# .vscode/mcp.json\n{mcp_servers_json(checkout, top='servers', stdio_type=True)}",
            "none: start the loop another way",
        ),
        Agent(
            "opencode",
            "opencode",
            "`AGENTS.md`",
            f"# opencode.json\n{opencode}",
            'opencode run "Run one round of the loop as AGENTS.md says"',
        ),
        Agent(
            "amp",
            "Amp",
            "`AGENTS.md`",
            f"amp mcp add loopcaptain -- {command}",
            'amp -x "Run one round of the loop as AGENTS.md says"',
        ),
        Agent(
            "other",
            "Any other agent with MCP",
            "its own instruction file; point it at `AGENTS.md`",
            f"# the usual mcpServers block, in the file the agent reads\n{mcp_servers_json(checkout)}",
            "the agent's own non-interactive command",
        ),
        Agent(
            "none",
            "An agent without MCP, or a script",
            "-",
            "no server: copy `standard/loops.py` into the loop,\n"
            "or call `loopcaptain emit <loop> <event> key=value`",
            "the script itself",
        ),
    ]


def agent(key: str, checkout: str) -> Agent:
    key = ALIASES.get(key, key)
    found = next((item for item in agents(checkout) if item.key == key), None)
    if found is None:
        raise KeyError(f"no agent {key!r}; one of {', '.join(item.key for item in agents(checkout))}")
    return found


def markdown(checkout: str = "") -> str:
    """The "Works with every agent" page: the lines for the installed command, as most readers have it."""
    parts = [
        "# Works with every agent",
        "",
        "The protocol names no vendor: a loop writes its files, whatever runs it. Around it, each",
        "agent adds the MCP server its own way. The server is `loopcaptain mcp`, over stdio. It needs",
        "the MCP extra, which a plain install leaves out: `uv tool install 'loopcaptain[mcp]'`.",
        "",
        "The lines below are for the installed command. From a checkout of the repository the server",
        f"is `{' '.join(server_argv('<checkout>'))}`, and `loopcaptain mcp-config <agent>`, run",
        "there, prints the line with that.",
        "",
        f"Taken from each agent's documentation as of {CHECKED}. Agents change their commands: where a",
        "line fails, the agent's own documentation wins, and a report of what works is welcome.",
        "",
        "This page is written by `make docs-pages` from `src/loopcaptain/agents.py`; edit that, not",
        "this. `loopcaptain mcp-config <agent>` prints one block.",
    ]
    for item in agents(checkout):
        parts += [
            "",
            f"## {item.name}",
            "",
            f"Reads by itself: {item.reads}.",
            "",
            "Add the server:",
            "",
            "```text",
            item.add,
            "```",
            "",
            f"Unattended, as `commands.start`: `{item.headless}`",
        ]
    return "\n".join(parts) + "\n"
