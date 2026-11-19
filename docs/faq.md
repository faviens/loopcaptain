---
title: "Questions about monitoring and steering agent loops"
description: "Short answers: what an agent loop is, how to monitor and stop one, how a human stays in the loop, which agents work, and what leaves the machine."
---

# Questions and answers

## What is an agent loop?

A program that hands work to an AI agent again and again until a goal is
met or a limit is reached: a plan, the work, a review, a verdict, and then
the next round. A Ralph loop (a shell loop around one prompt), Claude
Code's `/loop`, a research script that calls a model every round and a
long-running agent session are all agent loops.

## How do I monitor an agent loop that runs for hours?

Let it write what happens into `.loops/<loop-id>/events.jsonl` in its own
repository, one line per event, and open the board. The board shows every
loop on the machine: which round it is in, what each step found, what it
cost, and whether it still moves. A Python loop pastes a helper of under
110 lines, a shell loop calls `loopcaptain emit`, an agent session uses
the MCP server. [Connect or build a loop](connect.md) has the steps.

## How do I stop or steer a running agent loop?

Press Stop on the loop's page, answer its question with a button, or type
a note for the next round. The board appends a signed line to the loop's
`inbox.jsonl`; the loop reads it at the start of a round and acts on it.
The signature lets the loop tell your line from one an agent wrote into
the file. See [The board](board.md).

## How do I keep a human in the loop without watching a chat window?

A loop asks with a `question` event and either goes on with a default or
stands still until you answer. The board lists what waits for you, counts
it in the tab's title and can notify you through the browser. You answer
when you look, and the loop takes the answer at its next round.

## How do I monitor a Ralph loop?

Two commands in the shell loop: `loopcaptain emit` for each round and
step, `loopcaptain inbox` to read your stop and notes. A complete
`loop.sh` is on [Monitor a Ralph loop or any shell loop](shell-loop.md).

## Which coding agents does it work with?

Any. The protocol is plain files, so whatever can write a file can
report: Claude Code, Codex, Gemini CLI, Cursor, opencode, Amp, or a
script that calls a model's API. [Works with every agent](agents.md)
lists how each adds the MCP server.

## Does a loop have to install or import Loopcaptain?

No. A loop writes three small files; the helper is pasted text that uses
the Python standard library only. The board is installed once per
machine: `uv tool install loopcaptain`.

## Does anything leave my machine?

No. The board listens on `127.0.0.1` only, loads nothing from another
origin and sends nothing anywhere. It reads files in the repositories you
tell it to watch and writes only the inbox lines you send. The
[threat model](security.md) says what it reads, runs and writes.

## How is this different from tracing and observability tools?

Those record what a model call did, for later analysis, usually in a
hosted service. Loopcaptain shows where a loop stands now, round by
round, and carries your answer back into it; it runs on your laptop and
keeps its data in your repositories. The two fit together: a loop's
events map onto OpenTelemetry, see [OpenTelemetry](opentelemetry.md).

## What does it cost?

Nothing. Apache License 2.0, no account, no service. The example loop
that `loopcaptain demo` writes calls no model, so trying it is free too.

## How do I see every loop without opening a browser?

`loopcaptain status` prints one line per loop in the terminal: its
status, its round, its last line and what it asks.

## How do I take a finished or dead loop off the board?

`loopcaptain hide <repository> <loop>` takes one loop off the first page
and out of the figures; `unhide` brings it back. Loops that ended are
folded away by themselves, and one that died weeks ago is marked old and
no longer counts as needing a look.
