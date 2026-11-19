<!-- Written by scripts/docs_pages.py from the code: `make docs-pages`. Do not edit. -->

# The command line

`loopcaptain <command>`; from a checkout, `uv run loopcaptain <command>`.

## `serve`

The board on 127.0.0.1.

```text
loopcaptain serve [-h] [--port PORT]
```

| Argument | Meaning |
|---|---|
| `--port` | the port on 127.0.0.1, default 8484 |

## `validate`

Check a repository's .loops folders.

```text
loopcaptain validate [-h] [--strict] repo
```

| Argument | Meaning |
|---|---|
| `repo` |  |
| `--strict` | count warnings as problems |

## `emit`

Append one event: loopcaptain emit <loop> <event> key=value ....

```text
loopcaptain emit [-h] [--repo REPO]
                        loop
                        {round_started,step_started,step_finished,finding_closed,round_finished,question,question_closed,check,inbox_read,loop_started,loop_stopped,heartbeat}
                        [fields ...]
```

| Argument | Meaning |
|---|---|
| `loop` |  |
| `event` |  |
| `fields` | key=value; a value is read as JSON where it parses (round=2, blocks=true, ids='["a"]'), and as text where the field is text (commit=1234567) |
| `--repo` |  |

## `schema`

Write the protocol as json schema.

```text
loopcaptain schema [-h] target
```

| Argument | Meaning |
|---|---|
| `target` |  |

## `doctor`

Send a loop a stop and check that it takes it and ends.

```text
loopcaptain doctor [-h] [--timeout TIMEOUT] repo loop
```

| Argument | Meaning |
|---|---|
| `repo` |  |
| `loop` |  |
| `--timeout` | seconds to wait, default 600 |

## `watch`

Add a repository, or with --root a folder of them, to the board.

```text
loopcaptain watch [-h] [--root] path
```

| Argument | Meaning |
|---|---|
| `path` |  |
| `--root` | every sub-folder with .loops/ is a repository |

## `unwatch`

Take a folder off the board.

```text
loopcaptain unwatch [-h] path
```

| Argument | Meaning |
|---|---|
| `path` |  |

## `hide`

Take one loop off the board's first page and out of its figures.

```text
loopcaptain hide [-h] repo loop
```

| Argument | Meaning |
|---|---|
| `repo` |  |
| `loop` |  |

## `unhide`

Show a hidden loop on the first page again.

```text
loopcaptain unhide [-h] repo loop
```

| Argument | Meaning |
|---|---|
| `repo` |  |
| `loop` |  |

## `demo`

Write the example loop into a folder and watch it; costs nothing.

```text
loopcaptain demo [-h] [--target TARGET] [--no-watch]
```

| Argument | Meaning |
|---|---|
| `--target` |  |
| `--no-watch` | write it, but leave the config alone |

## `mcp-config`

How one coding agent adds the mcp server.

```text
loopcaptain mcp-config [-h] [--checkout CHECKOUT] [--markdown] [agent]
```

| Argument | Meaning |
|---|---|
| `agent` | claude-code, codex, gemini, cursor, ... |
| `--checkout` | the folder of this repository, if run from one |
| `--markdown` | print the page for every agent |

## `spec`

Print loops.md, the protocol to paste into a loop.

```text
loopcaptain spec [-h]
```

## `mcp`

Run the mcp server on stdio.

```text
loopcaptain mcp [-h]
```
