# Works with every agent

The protocol names no vendor: a loop writes its files, whatever runs it. Around it, each
agent adds the MCP server its own way. The server is `loopcaptain mcp`, over stdio.

The lines below are for the installed command. From a checkout of the repository the server
is `uv run --project <checkout> loopcaptain mcp`, and `loopcaptain mcp-config <agent>`, run
there, prints the line with that.

Taken from each agent's documentation as of 2026-11-15. Agents change their commands: where a
line fails, the agent's own documentation wins, and a report of what works is welcome.

This page is written by `make docs-pages` from `src/loopcaptain/agents.py`; edit that, not
this. `loopcaptain mcp-config <agent>` prints one block.

## Claude Code

Reads by itself: `CLAUDE.md` (import `AGENTS.md` with a line `@AGENTS.md`).

Add the server:

```text
claude mcp add loopcaptain -- loopcaptain mcp
```

Unattended, as `commands.start`: `claude -p "Run one round of the loop as AGENTS.md says" --output-format json`

## Codex CLI

Reads by itself: `AGENTS.md`.

Add the server:

```text
codex mcp add loopcaptain -- loopcaptain mcp

# or in ~/.codex/config.toml:
[mcp_servers.loopcaptain]
command = "loopcaptain"
args = ["mcp"]
```

Unattended, as `commands.start`: `codex exec --json "Run one round of the loop as AGENTS.md says"`

## Gemini CLI

Reads by itself: `GEMINI.md` (import `AGENTS.md` with a line `@AGENTS.md`).

Add the server:

```text
gemini mcp add loopcaptain loopcaptain mcp

# or in .gemini/settings.json:
{
  "mcpServers": {
    "loopcaptain": {
      "command": "loopcaptain",
      "args": [
        "mcp"
      ]
    }
  }
}
```

Unattended, as `commands.start`: `gemini -p "Run one round of the loop as AGENTS.md says" --output-format json`

## Cursor

Reads by itself: `AGENTS.md`, `.cursor/rules/`.

Add the server:

```text
# .cursor/mcp.json
{
  "mcpServers": {
    "loopcaptain": {
      "command": "loopcaptain",
      "args": [
        "mcp"
      ]
    }
  }
}
```

Unattended, as `commands.start`: `cursor-agent -p "Run one round of the loop as AGENTS.md says" --output-format json`

## VS Code (Copilot agent mode)

Reads by itself: `AGENTS.md`, `.github/copilot-instructions.md`.

Add the server:

```text
# .vscode/mcp.json
{
  "servers": {
    "loopcaptain": {
      "type": "stdio",
      "command": "loopcaptain",
      "args": [
        "mcp"
      ]
    }
  }
}
```

Unattended, as `commands.start`: `none: start the loop another way`

## opencode

Reads by itself: `AGENTS.md`.

Add the server:

```text
# opencode.json
{
  "mcp": {
    "loopcaptain": {
      "type": "local",
      "command": [
        "loopcaptain",
        "mcp"
      ],
      "enabled": true
    }
  }
}
```

Unattended, as `commands.start`: `opencode run "Run one round of the loop as AGENTS.md says"`

## Amp

Reads by itself: `AGENTS.md`.

Add the server:

```text
amp mcp add loopcaptain -- loopcaptain mcp
```

Unattended, as `commands.start`: `amp -x "Run one round of the loop as AGENTS.md says"`

## Any other agent with MCP

Reads by itself: its own instruction file; point it at `AGENTS.md`.

Add the server:

```text
# the usual mcpServers block, in the file the agent reads
{
  "mcpServers": {
    "loopcaptain": {
      "command": "loopcaptain",
      "args": [
        "mcp"
      ]
    }
  }
}
```

Unattended, as `commands.start`: `the agent's own non-interactive command`

## An agent without MCP, or a script

Reads by itself: -.

Add the server:

```text
no server: copy `standard/loops.py` into the loop,
or call `loopcaptain emit <loop> <event> key=value`
```

Unattended, as `commands.start`: `the script itself`
