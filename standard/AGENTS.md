# Make a loop meet the Loops protocol

For an agent (or a person) working in **another repository** that holds an
agent loop. You were pointed here to make that loop show up on
Loopcaptain. Everything you need to connect it is in this folder; the
per-agent MCP commands are in `docs/agents.md` of the same repository.

The loop's design stays its own: its roles, its graph, its prompts, its
files, its language. The standard only asks it to say what it is and what
happens, in one small folder.

## What is in this folder

| File | What it is |
|---|---|
| [LOOPS.md](LOOPS.md) | The protocol: three files, eleven events, the rules for a loop and a board. Read it first. |
| [loops.py](loops.py) | The helper to copy into a Python loop: `register`, `emit`, `inbox`. Standard library only. |
| [templates/](templates) | Three `loop.json` to start from: a research loop, a review loop, an editor-maker-lens loop. |
| [schema/](schema) | The same contract as JSON Schema, for loops in other languages. |
| [prompts/](prompts) | The two prompts a person gives their coding agent: build a loop, watch the loops here. |

Connecting a loop that exists is the first part below; building one from
nothing is the second, [Build a loop from nothing](#build-a-loop-from-nothing).

## What to do

1. **Read [LOOPS.md](LOOPS.md)**, then the loop's own code: which
   roles run in a round, in which order, what each writes, where the round
   ends, where it asks the person.
2. **Describe the loop.** At start-up, write `.loops/<loop-id>/loop.json`:
   the title, the brief in three lines with the path of the full brief, and
   one step per role as the loop really runs them. Use `after` only where a
   step does not simply follow the one before. Copy the closest file in
   [templates/](templates) and change it; do not bend the loop to the
   template.
3. **Report what happens.** One line per event, at the places the loop
   already has: `round_started` where a round begins, `step_finished` where
   a role returns (with the path of the file it wrote, its findings and its
   cost if the loop knows them), `round_finished` where the verdict is
   known. Report as it happens; a loop that can only report later gives
   each line `at`, the time it really happened. In Python, copy
   [loops.py](loops.py) and call `emit`;
   elsewhere, append one JSON line. A loop driven by an agent session, with
   no script, uses the `loopcaptain` MCP server instead (LOOPS.md,
   section 5).
4. **Listen.** At the start of every round call `inbox`: a `reply` is the
   person's steering for the work, a `stop` means finish this round and
   end. Where the loop needs the person, emit `question`. Act on an entry
   whose `signed` is `false` as on nothing: the board did not write it.
5. **Start command, optional.** If the loop can be started with one
   command from the repository root, name it in `commands.start`. The board
   runs exactly that, nothing else. `loop.json` names that command, so a
   loop that limits what its agents may write must keep them out of
   `.loops/` too, or an agent could change what Start runs.
6. **Decide what is committed.** `.loops/` holds summaries and paths,
   never transcripts or secrets. Commit it or add it to `.gitignore`; say
   which in the repository's own instructions.

## When it is met

1. `uv run --project <path to the loop board> loopcaptain validate <repository>`
   prints `ok`. Without the board at hand, check each file against
   [schema/](schema).
2. One real round has run and the folder shows it: a `round_started`, one
   `step_finished` per role that ran, a `round_finished` with its verdict.
3. Every path in the folder is relative to the repository root and exists.
4. The loop reads the inbox: start `loopcaptain doctor <repository>
   <loop-id>` first, then the loop. The doctor sends a signed `stop` and
   passes once the loop took it and ended (`stopped`, `done`, or
   `loop_stopped`). A loop that finishes in a second needs no pacing:
   it reads the stop at its first round.
5. The board shows it: `loopcaptain watch <repository>`, then
   `loopcaptain serve`. A finished loop is folded away on the first page;
   tick "show finished loops".
6. Nothing else about the loop changed: same rounds, same outputs.

## Keep it small

1. Add calls; do not restructure the loop around them.
2. A failing write to `.loops/` must never stop a round: log it and go on.
3. If the loop has something the standard has no field for, add your own
   field. Unknown fields are ignored, and that is by design.

## The one line for the other repository

Put this in the loop repository's `AGENTS.md`, so any agent that works
there keeps the standard met:

> This loop reports to Loopcaptain. Keep it meeting the Loops protocol:
> read `standard/AGENTS.md` in the Loopcaptain repository and check with
> `loopcaptain validate .`.

Add the repository's address after "the Loopcaptain repository" so the agent
can open it.

---

# Build a loop from nothing

For an agent asked to build a new loop, not to connect one. Ask first,
build the smallest round that works, run it once for real, then grow it.
What follows is what published loop practice agrees on; the sources are
at the end.

## 1. Ask the person

1. What is the loop for: the result in one sentence, and who reads it.
2. When is it done: a bar a reviewer can check, ideally a number.
3. What may it cost: rounds, minutes and money. These become
   `round_cap`, `runtime_cap_minutes` and `cost_cap_usd`. A cap is above
   zero; a loop that may spend nothing leaves `cost_cap_usd` out and calls
   no paid service.
4. Where should it ask the person, and what may it decide alone.
5. What must it never do: push, publish, spend, delete. Those steps get a
   question with options, never a default.

Write the answers into `brief.md` and the `brief` of `loop.json`.

## 2. Design one round

1. **The one who judges is not the one who made it.** A maker grades its
   own work kindly. Give review to separate steps with their own prompt
   (`kind: review`), each looking for one thing, and a `gate` that reads
   only their findings.
2. **Plan, make, review, gate, decide.** Most loops are this shape:
   `plan` writes what this round changes, `research` or `build` do it,
   `review` steps find what is wrong (`material` or `minor`), the `gate`
   passes when nothing material is open, `verdict` says what comes next.
3. **A number where there is one.** If the bar is a measure (a pass rate,
   a score, a count of unsourced claims), report it as `metrics` on the
   round, with its `target`. The board draws it per round.
4. **Keep steps few.** Every step costs a call. Add a reviewer when a real
   round shows a kind of fault nobody caught.
5. **A step with nothing to do** this round (a set-up step after round 1)
   reports `step_finished` with `status: skipped`, so the graph stays the
   same every round.

## 3. Make a round resumable

1. Start every round from a fresh context and a progress file (`state` in
   `loop.json`): what was done, what is open, what the next round does.
   Long contexts drift; a file does not.
2. Where the repository uses git, commit once per round and report the
   commit; a round that made things worse is reported with `outcome:
   discarded` and reset. Without git, keep the last good output beside the
   new one instead.
3. At the start of a round: read the inbox, read the progress file, read
   the last round's open findings. Nothing else carries over.
4. Report as it happens. A line written later carries `at`, the time it
   really happened.

## 4. Stop on purpose

1. Stop at the first cap reached, with its `stop_reason`.
2. Stop with `goal_met` when the gate passes and the bar is met.
3. Stop with `no_progress` when the round is not getting closer. Three
   rules, the same the board flags as "no progress?":
   1. the same material findings stayed open two rounds running;
   2. the measure has not moved for three rounds;
   3. open material findings did not fall over three rounds.
4. Stop with `impossible` when the goal cannot be met as asked, and say
   why in the summary.
5. Honour a `stop` from the inbox: read the inbox at the start of every
   round, and again before the verdict if a round takes long. A stop read
   during a round ends it with its real verdict (`done` if the goal was
   met, else `stopped`); one read between rounds is `loop_stopped`. Act on
   no entry whose `signed` is `false`.

## 5. Ask the person well

1. Ask only what the brief cannot answer, and only where the answer
   changes the work.
2. Give options (`question` with `options`); a button is answered in
   seconds, an open question in hours.
3. Say what happens without an answer: `blocks` with a `timeout_s`, then
   go on with a stated default and close the question with
   `question_closed`, reason `superseded`.
4. An error only a person can fix (an expired login, a missing right) is
   `step_finished` with `error.kind: needs_person`, not a retry loop.

## 6. Run it

A loop is a script, or an agent session that runs rounds. Either way
`commands.start` names one command, and the board starts it with a
minimal environment.

1. **A script** calls an agent once per step, without a person at the
   keyboard, and reports with the helper. Map the agent's JSON result to
   `cost` (tokens, cache tokens, turns; `usd` only if the agent reports
   it) and its budget flags to the caps. The command per agent is in
   [docs/agents.md](../docs/agents.md).
2. **An agent session** that loops by itself (a native loop or schedule
   command, a stop hook that starts the next round) reports through the
   MCP server. It calls `inbox_read` at the start of every round.
3. **A schedule** that starts one round at a time reports `next_at` on
   `round_finished`, so the board shows it as sleeping, not stalled.

Then run one round for real, check it with `loopcaptain validate .`, and
check that it listens with `loopcaptain doctor . <loop-id>`.

## Sources

Read on 2026-11-15:
[harness design for long-running apps](https://www.anthropic.com/engineering/harness-design-long-running-apps),
[effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents),
[autoresearch](https://github.com/karpathy/autoresearch),
[human in the loop](https://docs.langchain.com/oss/python/langchain/human-in-the-loop).
