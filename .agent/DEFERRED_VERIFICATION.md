# Deferred verification

Changes no real run has shown working yet. A row leaves when its evidence
is named in the commit that closes it.

| Commit | Change | Risk | Evidence that would close it |
|---|---|---|---|
| the MCP door | The MCP server ran over stdio against the SDK's own client (register, a round, a question, a refused call), not from a live agent session | An agent may use the tools differently than the docstrings intend, or skip calls | the server added as `loopcaptain mcp-config <agent>` prints, for two agents of different vendors, then one round reported from each session and seen on the board |
| the protocol | The example loop and one loop a fresh agent built from the first prompt (2026-11-15, validate ok, doctor passed, on the board) have written it; no real loop with real costs and long reviews has | Fields real rounds need may be missing; long summaries may crowd the round table | One round of a real loop (F1) shown on the board |
| the board | Looked at in Chrome, light and dark, at 1360 px, and at 390 px with device emulation (every page fits since 600eca2); not in Safari or Firefox, no keyboard-only pass, no automated accessibility run | Layout, focus or contrast faults outside Chrome | The pages opened in Safari and Firefox; a keyboard-only pass; a Lighthouse accessibility run |
| ci/hardening | The workflows (three Pythons and macOS, security, scorecard, links, release, docs) passed zizmor, actionlint and the workflow schema; none has run on GitHub | A runner difference, a missing environment or a Pages setting fails the first run | The branch pushed, CI green on a pull request; the docs workflow publishing once |
| the agents page | `docs/agents.md` follows a table read from each agent's documentation in the review of 2026-11-15; the entries for Gemini CLI, Cursor, opencode and Amp could not be confirmed in that review, and no line has been run | A wrong flag or file name sends a stranger the wrong way | The first prompt run in two agents of different vendors, each ending with a loop on the board |
| the phone host name | `serve --host-name` answered 200 to the named host and 400 to another, over curl with a set Host header; not yet behind a real `tailscale serve` on a phone | Tailscale may forward a Host header other than the bare name, and the board would refuse every phone request | The board opened and a stop sent from a phone over `tailscale serve` |
