# protocol/: the standard as code

Read [the root AGENTS.md](../../../AGENTS.md) first. This folder is the
code twin of [standard/LOOPS.md](../../../standard/LOOPS.md): if
the text and this folder disagree, both are wrong until a test says which.

| File | Holds |
|---|---|
| `models.py` | The Pydantic models of the loop's files: `Manifest` (`loop.json`), the events (`events.jsonl`), `InboxEntry` (`inbox.jsonl`). Frozen; unknown fields ignored |
| `store.py` | Reading and writing a loop's folder: atomic `loop.json`, append-only lines, bad lines reported as `Problem`, never fatal |
| `state.py` | `fold`: manifest + events + inbox + a clock -> `LoopState` (rounds, runs, findings, items, status). Pure |
| `validate.py` | `loopcaptain validate`: what a folder gets wrong, one line each |
| `__init__.py` | `spec_text()`: the standard's text, for the board's Connect page and the MCP tool |

Rules here:

1. A new field or event: add it to `models.py`, to the tables of
   `LOOPS.md`, run `make schema`, and add a test that folds it.
2. Optional with a default, always. A loop written yesterday must still
   validate (root rule 3).
3. `state.py` takes the time as an argument and reads no file: keep it
   pure, so status rules stay testable.
4. Reading never raises on a loop's bad line. Writing validates first.
5. Nothing in this folder imports `board/` or `mcp_server/`.
