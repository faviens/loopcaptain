# Loopcaptain

**An open protocol for agent loops and a local dashboard to monitor and
steer them: one board for every agent loop.** A loop, in its own repository, writes
three small files; the board shows what it is for, where it stands, what
every round and reviewer found, what it cost, and what waits for you. You
answer and steer from the board.

![The board: a loop waits for an answer and offers two buttons](assets/screenshot-overview.webp)

## Copy one of these into your coding agent

```text
--8<-- "standard/prompts/build-a-loop.md"
```

```text
--8<-- "standard/prompts/watch-my-loops.md"
```

Or [install it](installation.md) and [get started](get-started.md) with
the example loop, which costs nothing.

## How it works

![How it works. On the left, a loop in any repository: a script that pastes the helper from LOOPS.md, or an agent session that uses the MCP server. Both write the loop's folder, .loops/loop-id, with three files: loop.json, events.jsonl and inbox.jsonl. On the right, the board on this machine reads the folder and shows every loop, one loop in detail, and the protocol to copy. Your answer, a stop or a start goes back through inbox.jsonl, which the loop reads at its next round.](assets/hero-light.svg)
