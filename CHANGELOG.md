# Changelog

What changed for someone who uses Loopcaptain. Newest first.

## Unreleased

### Security

1. Start passes a started loop only `PATH`, `HOME`, `LANG`, `TERM` and `LOOPCAPTAIN_INBOX_KEY`,
   not the board's whole environment, and asks for a tick the first time
   a given command of a given repository is run.
2. The board signs every inbox line (`sig`, an optional field of
   protocol 1) with a key outside every repository; the helper and the
   MCP tool `inbox_read` say whether an entry is `signed`, so a loop can
   refuse a forged stop or reply. Each line names its loop, and the
   board's own status ignores a line whose signature fails.
3. The file viewer refuses credential files (`.netrc`, `*.pem`, `id_rsa*`
   and more) and shows content only for known text files.
4. The board follows no symbolic link in a loop's folder, and the MCP
   tools write only under their working folder or `LOOPCAPTAIN_MCP_ROOTS`.

### Changed

1. The demo is one example loop that builds a dashboard on loop
   engineering: it asks once with buttons, converges over four rounds,
   and honours only a signed stop. `loopcaptain demo` writes it from an
   installed package; its history is the loop itself run with past times.
2. `loopcaptain validate` also checks that artifact paths exist, that time
   does not run backwards and that a round has one outcome; it warns of
   rounds written after the fact and of loops that never read their
   inbox. Problems and warnings are printed apart; `--strict` fails on
   warnings too.
3. `loopcaptain doctor <repository> <loop-id>` sends a running loop a
   signed stop and passes once the loop took it and ended: the one way to
   know a loop listens.
4. `loopcaptain watch <folder>` and `unwatch <folder>` edit the board's
   config, so the board needs no checkout.

### Added

1. A documentation site (Zensical): get started, connect or build a loop,
   every agent, the board, the protocol, a reference written from the
   code, security, architecture. `make docs` builds it and joins
   `make check`; `llms.txt` points agents at the standard.
2. The README opens with two prompts to copy into any coding agent (build
   a loop, watch the loops on this machine), kept once in
   `standard/prompts/`; `AGENTS.md` section A is the runbook the second
   one points at, and `standard/AGENTS.md` a guide to building a loop.
3. `loopcaptain mcp-config <agent>` and `docs/agents.md`: how each coding
   agent adds the MCP server and runs a loop unattended.
4. Protocol 1 grows, every field optional: `at` for the real time of an
   event, a round's whole `cost`, cache tokens and turns, `metrics`,
   `attempt`, `error` (`needs_person` waits for you), `session`,
   `outcome` (kept or discarded), `next_at`, question `id` and
   `options`, `workspace` and `state` in `loop.json`, and the events
   `question_closed`, `loop_stopped` and `heartbeat`.
5. A loop that said when it is back shows as `sleeping`, not stalled.
6. The board flags "no progress?" before the loop does: the same
   material findings open two rounds running, a measure flat for three
   rounds, open findings that do not fall.
7. The overview groups loops by repository, with a "Waiting" tab for
   questions; worktrees of one repository show once, from the one
   written last.
8. The loops protocol, version 1: a loop writes `loop.json` and
   appends to `events.jsonl` in `.loops/<loop-id>/`; the board appends
   to `inbox.jsonl`. Eight events: `round_started`, `step_started`,
   `step_finished`, `finding_closed`, `round_finished`, `question`,
   `check`, `inbox_read`.
9. `standard/`: the text, a helper of 50 lines to paste, three `loop.json`
   templates, the JSON Schema, and an `AGENTS.md` for the agent that
   connects a loop.
10. The board: all loops with what waits for you on top; one loop with its
   brief, the graph of a round, every round against every step, a round in
   detail, the items it evaluates; a page to copy the standard from.
11. Steering from the board: answer a question, send a note, stop after the
   current round, start the command a loop declares.
12. The `loopcaptain` command: `serve`, `validate`, `emit`, `schema`, `spec`,
   `mcp`.
13. An MCP server with the protocol as five tools (`protocol`,
   `loop_register`, `emit`, `inbox_read`, `loop_status`), for loops an
   agent session drives.
14. `make demo`: three invented loops, one of them startable, that cost
   nothing.
15. The overview draws each loop's latest twelve rounds beside its round
   count: a square per round, darker for more findings left open, a green
   dot for none, a ring while it runs. A loop that converges is seen
   without opening it.
16. The documentation has an Installation page (one command from the
   repository, with uv, pipx or pip), a five-minute Get started with the
   example loop, and a Setup page: what the board watches, how to check a
   loop, and what to look at when a loop does not show.
