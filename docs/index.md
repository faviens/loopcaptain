# Loopcaptain

**An open protocol for agent loops and a local dashboard to monitor and
steer them: one board for every agent loop.** A loop, in its own repository, writes a few small files; the board shows what it is for, where it stands, what
every round and reviewer found, what it cost, and what waits for you. You
answer and steer from the board.

![The board's front page with eight invented loops in four projects: one waits for an answer, two run, one stalled and one failed are marked, each with its rounds, open findings, time and cost.](assets/screenshot-overview.webp)

Invented loops, photographed from the board itself.

## Get started

**Look first.** [Install it](installation.md) and [get started](get-started.md)
with the example loop, which costs nothing: no model, no network.

**Monitor the loops you already run.** Paste this into your coding
agent, whichever you use. It finds the loops on your machine, sets up the
board and proposes the smallest change that connects each one:

```text
--8<-- "standard/prompts/watch-my-loops.md"
```

**Set up a new loop that speaks the protocol.** Paste this one. It
asks what the loop is for, builds it in your repository and shows you one
real round on the board:

```text
--8<-- "standard/prompts/build-a-loop.md"
```

## What you see

![Waiting for you: a loop's question with two answer buttons and a box for your own words.](assets/screenshot-waiting.webp){ width="49%" }
![One loop: key figures, rounds against the cap, and a line per measure showing whether it converges.](assets/screenshot-loop.webp){ width="49%" }

![The rounds of one loop: every round against every step, and one round with what each step did, found and cost.](assets/screenshot-rounds.webp){ width="49%" }
![Open findings of one loop: what the last reviewed round left open, by reviewer.](assets/screenshot-findings.webp){ width="49%" }

[The board](board.md) walks through each page.

## How it works

![How it works. On the left, a loop in any repository: a script that pastes the helper from LOOPS.md, or an agent session that uses the MCP server. Both write the loop's folder, .loops/loop-id, with loop.json, events.jsonl and inbox.jsonl. On the right, the board on this machine reads the folder and shows every loop, one loop in detail, and the protocol to copy. Your answer, a stop or a start goes back through inbox.jsonl, which the loop reads at its next round.](assets/hero-light.svg)
