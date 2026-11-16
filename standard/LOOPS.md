# Loops protocol, version 1

How an agent loop says what it is and what happens in it, so that a board
can show it and a person can steer it. This file is the whole interface:
paste it into the repository of a loop, or hand it to the agent that
writes the loop. Nothing else is needed.

A loop keeps one small folder in its own repository. It says once what it
is, then appends one line for each thing that happens. A board reads that
folder and writes the person's answers into it. No server, no dependency, no
network: a loop in any language that can write a file can do this. The
protocol names no tool, vendor or model.

```
<repository>/.loops/<loop-id>/
    loop.json       what the loop is            written by the loop
    events.jsonl    what happened, line by line appended by the loop
    inbox.jsonl     what the person sends       appended by the board
```

`<loop-id>` is lowercase letters, digits, `.`, `-`, `_`. A repository may
hold several loops, one folder each. A run that counts its rounds from 1
again (a new branch, a fresh start) is a loop of its own, with its own id
such as `review-run-3`, so the rounds of two runs never mix. Whether `.loops/` is committed or
ignored is the repository's choice.

## 1. `loop.json`: what the loop is

Written when the loop starts; writing it again replaces it. A `loop.json`
that is not valid JSON is still a loop: a board lists it as unreadable and
says what the parser said.

```json
{
  "protocol": 1,
  "id": "market-scan",
  "title": "Market scan of field service tools",
  "brief": {
    "goal": "Which three tools should the client try first?",
    "audience": "The head of operations",
    "bar": "She can name the three and say why",
    "path": "brief/brief.md"
  },
  "steps": [
    {"id": "plan", "kind": "plan", "name": "Editor plans", "backend": "agent-cli", "model": "large"},
    {"id": "research", "kind": "research", "purpose": "One agent per angle", "backend": "another-agent-cli"},
    {"id": "build", "kind": "build", "prompt": "prompts/build.md"},
    {"id": "facts", "kind": "review", "after": ["build"], "purpose": "Every number has a source"},
    {"id": "reader", "kind": "review", "after": ["build"], "purpose": "Reads as the audience"},
    {"id": "gate", "kind": "gate", "after": ["facts", "reader"]},
    {"id": "verdict", "kind": "verdict"}
  ],
  "round_cap": 12,
  "cost_cap_usd": 60,
  "pace": "stops when it needs the person",
  "commands": {"start": "make loop ROUNDS=3"},
  "outputs": [{"name": "memo", "path": "out/memo.md"}],
  "workspace": {"branch": "loop/market-scan", "worktree": "../market-scan-loop"},
  "state": [{"name": "progress", "path": "work/progress.md"}]
}
```

Only `protocol` and `id` are required. The rest:

1. `brief`: the goal, the audience and the bar for done in a line each, and
   the path of the full brief.
2. `steps`: the roles of one round, in order. This is the graph the board
   draws. `kind` is one of `plan`, `research`, `analyse`, `build`, `review`,
   `gate`, `verdict`, `other`. A step follows the one listed before it;
   give `after` only where that is not so (two reviewers that both follow
   `build`, a gate that waits for both). `name`, `purpose`, `prompt` (a
   path), `backend` and `model` are shown as given. `backend` is whatever
   runs the step: the name of an agent's command line, a script, a
   person. The protocol knows no vendor.
3. `round_cap`, `runtime_cap_minutes`, `cost_cap_usd`: the loop's own
   limits. It stops at whichever comes first; the board shows them.
4. `commands.start`: the one command the board may run, in the repository
   root, when the person presses Start. Leave it out and the board has no
   Start button for this loop.
5. `outputs`: what the loop makes, by path.
6. `workspace`: the branch and worktree the loop runs in, and `state`:
   the files one round hands to the next (a progress note, a feature
   list). Both are shown as text to copy, so a person can pick the loop up
   by hand; the board runs neither.

Every path in the protocol is relative to the repository root.

## 2. `events.jsonl`: what happened

One JSON object per line, appended, never rewritten. A line ends at the
newline character (`\n`) and at nothing else: split on that alone, since a
text may hold other characters that some languages also call a line break
(U+2028, U+2029, U+0085). Every line has `ts`
(UTC, `2026-11-14T21:03:00Z`, fractions of a second allowed:
`2026-11-14T21:03:00.250Z`), the time the line was written, and
`event`. Any line may carry `at`: the time the thing really happened, for
a loop that reports later than it works. Durations are measured on `at`
where it is given, so a round written after the fact keeps its real
times. A time without a zone is read as UTC. Any year is read, `9999`
for "never" included; a `next_at` holds at most a week after its line.
A number that is not finite (`Infinity`; `NaN` where the field has no
lower bound) is read too, and counted as absent: a cost of it adds nothing, a measure of it is not
drawn, a cost cap of it is no cap. `validate` warns of both. A line
stamped more than a few minutes ahead of the reader's clock is read, but
is no sign that the loop is alive, and its `next_at` no promise, until
its time has come.

| `event` | Fields | When |
|---|---|---|
| `round_started` | `round`, `plan`, `artifact` | A round begins. `plan` is a few lines. |
| `step_started` | `round`, `step`, `label` | Optional: shows the step as running. |
| `step_finished` | `round`, `step`, `label`, `status`, `summary`, `artifact`, `findings`, `cost`, `metrics`, `attempt`, `error`, `session`, `model` | A step ends. |
| `finding_closed` | `round`, `step`, `id`, `label`, `resolution`, `reason` | A finding of this round is settled. |
| `round_finished` | `round`, `verdict`, `stop_reason`, `summary`, `next`, `commit`, `artifact`, `cost`, `metrics`, `outcome`, `next_at` | A round ends. |
| `question` | `text`, `round`, `blocks`, `timeout_s`, `id`, `options` | The loop needs the person. |
| `question_closed` | `question`, `reason`, `answer` | The loop ends its own question. |
| `loop_stopped` | `stop_reason`, `summary` | The loop ends between rounds. |
| `heartbeat` | `text`, `next_at` | Alive; when to expect the next line. |
| `check` | `item`, `kind`, `result`, `who`, `finding`, `evidence`, `round` | One check of one thing the loop evaluates. |
| `inbox_read` | `ids` | The loop has taken these inbox entries. |

A reader skips a line whose `event` it does not know and reads on: later
releases add events to this table, and a loop may write its own. Such a
line still needs `ts`, and still shows that the loop is alive.

1. `round` counts from 1. `step` is a step id from `loop.json`. A
   `round_started` for a round that already ran starts that round again,
   clean.
2. `label` tells runs of one step apart within a round: a research step
   with eight agents sends eight `step_finished`, each with its angle as
   `label`.
3. `status`: `ok`, `failed` or `skipped`. Left out, it is `ok`.
4. `summary`: one or two sentences. `artifact`: the path of the file the
   step wrote (the plan, the review, the gate report). The board links to it
   and never copies it.
5. `findings`: what a reviewer or a gate found, each
   `{"id": "1", "text": "...", "severity": "material"}`; `severity` is
   `material` or `minor`. Reviews are fresh each round: what is open is what
   the last round's reviews found and nobody closed. A step that reports
   again in the same round replaces what it reported before. In
   `finding_closed`, `label` names the run of a fan-out step; left out,
   the finding is closed in every run of the step. `resolution` says how
   it was settled: `fixed`, `accepted` (it stands, on purpose),
   `wontfix`, `false_positive` or `duplicate`; `reason` is a sentence.
6. `cost`: `{"usd": 0.34, "tokens_in": 162113, "tokens_out": 4784}`, any
   part of it, and `tokens_cache_read`, `tokens_cache_write`, `turns`, and
   `estimated: true` where the figures are the loop's guess. `usd` is
   optional: an agent on a subscription reports none, and the board then
   shows tokens. A `cost` on `round_finished` is the round's whole cost,
   for a loop that knows only the sum; the steps' costs are then not added.
7. `verdict`: what happens next. `continue` (another round follows),
   `done` (the goal is met), `wait` (the loop needs the person before it
   goes on), `stopped` (it ended without meeting the goal) or `failed`
   (the round broke). `stop_reason` says why where the verdict does not:
   `goal_met`, `round_cap`, `cost_cap`, `runtime_cap`, `person`,
   `no_progress`, `error` or `impossible` (the goal cannot be met as
   asked). `next` is the brief for the following round, `commit` the
   commit of this one. `outcome` is `kept` or `discarded`: a round whose
   work was thrown away, an experiment that made things worse. `next_at`
   is when the next round starts, for a loop that sleeps between rounds:
   the board shows it as sleeping, not stalled, until then, and at most a
   week ahead. A new round spends the promise.
8. `question`: `blocks` is `true` when the loop stands still until the
   answer comes, `timeout_s` how long it waits before it goes on without
   one. Left out, the loop goes on and reads the answer at its next round.
   A question is open until the person replies. A blocking question is
   also over once its `timeout_s` has passed or the loop starts another
   round: it went on. `id` names the question; `options`,
   `[{"id": "a", "label": "Forty people"}]`, become buttons, and the reply
   carries `question` and `choice`. `question_closed` ends a question the
   loop settled itself: `reason` is `answered` (elsewhere, `answer` says
   how), `superseded` (it went on with a default) or `withdrawn`;
   `question` is the id, left out the last open question.
9. `check`: for loops that evaluate a list of things (use cases, skills,
   features). `kind` is free text such as `desk research`, `own trial`,
   `workshop`, `automated test`; `result` is `pass`, `partly`, `fail` or
   `blocked`. A kind nobody ran for an item shows as an empty cell.
10. `metrics`: the numbers a loop optimises, on a step or a round,
    `[{"name": "pass rate", "value": 0.82, "target": 0.95, "better":
    "higher", "unit": ""}]`. The board draws each per round.
11. `attempt` counts tries of a step within a round from 1; `error`,
    `{"kind": "transient" | "needs_person", "text": "..."}`, says why it
    did not succeed. `needs_person` waits for the person like a blocking
    question, until they reply. `session` is the agent session the step
    ran in, shown as text so a person can resume it by hand. `model` is
    the model the step really ran on, where it is not the one `loop.json`
    names for the step: a fallback after the first one refused.
12. `loop_stopped`: the loop ended between rounds, say after a stop that
    came when no round was open. The last round's verdict stays as it was.
    While a round is open it ends nothing: finish the round first.
13. `heartbeat`: a loop that works quietly or sleeps says it is alive and,
    with `next_at`, when its next line comes. Until then it is not
    stalled.

A round of the example above, as lines:

```json
{"ts": "2026-11-14T21:00:00Z", "event": "round_started", "round": 3, "plan": "Close the two fact findings; add pricing."}
{"ts": "2026-11-14T21:04:10Z", "event": "step_finished", "round": 3, "step": "plan", "artifact": "work/rounds/3-plan.md", "cost": {"usd": 0.31}}
{"ts": "2026-11-14T21:09:40Z", "event": "step_finished", "round": 3, "step": "research", "label": "pricing", "summary": "List prices for five of six tools."}
{"ts": "2026-11-14T21:15:02Z", "event": "step_finished", "round": 3, "step": "facts", "artifact": "work/rounds/3-review-facts.md", "findings": [{"id": "1", "text": "The 40 percent figure has no source."}]}
{"ts": "2026-11-14T21:16:30Z", "event": "question", "round": 3, "text": "Is the budget per seat or per site?"}
{"ts": "2026-11-14T21:17:00Z", "event": "round_finished", "round": 3, "verdict": "continue", "summary": "Pricing is in; one fact is open.", "commit": "3fa3487"}
```

## 3. `inbox.jsonl`: what the person sends

The board appends; the loop only reads. Read it at the start of every
round, wherever the loop waits for the person, and once more before the
loop ends. That last read takes a stop sent during the final round: left
unread, it would be the first thing the next start reads, and that start
would end at once. A reply read that late is steering for the next start;
keep it in a file of the loop's own.

```json
{"id": "20261114T211900-a3f1", "ts": "2026-11-14T21:19:00Z", "kind": "reply", "text": "Per seat.", "round": 3, "sig": "9c1e..."}
{"id": "20261114T213000-09bc", "ts": "2026-11-14T21:30:00Z", "kind": "stop"}
```

1. `reply`: text for the loop. It answers the open question if there is
   one; without one it is steering for the next round. A reply to a
   question with an `id` carries `question`, and `choice`, the id of the
   option the person picked, where the question offered options.
2. `stop`: end. A stop read during a round: finish the round and send
   `round_finished` with its real verdict, `done` if the goal was met,
   else `stopped` with `stop_reason` `person`. A stop read between rounds,
   or in the last read before the loop ends: send `loop_stopped` and start
   no round, with `stop_reason` `goal_met` where the last round was `done`.

After acting on entries, append `inbox_read` with their ids so the board
shows them as read.

Every line the board writes carries `sig`, an HMAC-SHA256 in hex over the
line without `sig` (keys sorted, no spaces, as `json.dumps(...,
sort_keys=True, separators=(",", ":"), ensure_ascii=False)` writes it).
The line names its loop in `loop`, signed with the rest, so a line copied
into another loop's inbox does not verify there. The key is in the
board's config folder, `~/.config/loopcaptain/inbox.key`
or the file `LOOPCAPTAIN_INBOX_KEY` names, outside every repository. The
helper and the MCP tool add `signed` to each entry:

1. `true`: the board wrote it for this loop.
2. `false`: anything else did. A loop whose agents can write files SHOULD
   NOT act on it: it is not from the person.
3. `null`: nothing was checked, because the loop cannot read the key. No
   board has written to an inbox on this machine yet, or the loop runs
   somewhere the config folder is not visible (a container), or
   `LOOPCAPTAIN_INBOX_KEY` names another file. `null` is not `true`: a
   line from the person and a line from anyone else who can write the
   file look the same.

A loop SHOULD act only on entries whose `signed` is `true`. Where the key
cannot be read, make it readable to the loop (mount the file, or set
`LOOPCAPTAIN_INBOX_KEY`) rather than accept `null`; a loop that accepts
`null` anyway does so knowing that its inbox is then only as safe as its
repository. The helper writes a line to standard error whenever it hands
out an entry it could not check, so the case does not pass unseen.

A signature says who wrote a line, not when it still applies. The helper
and the MCP tool therefore add `stale` to each entry: `true` for a reply
that names a question (`question`) and was written before the loop last
asked that question. It answers an earlier asking, and a loop SHOULD NOT
take it as the answer to the present one.

## 4. The helper to paste

Standard library only, for Python 3.9 and later. Copy it into the loop as
`loops.py`; the same text is the file `loops.py` beside this one.

```python
"""Loops protocol 1: say what a loop is, what happened, and read the person's answers."""

import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def folder(loop_id, repo="."):
    path = Path(repo) / ".loops" / loop_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def register(loop_id, manifest, repo="."):
    """Write loop.json. `manifest` holds title, brief, steps and so on; id and protocol are set here."""
    target = folder(loop_id, repo) / "loop.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps({**manifest, "protocol": 1, "id": loop_id}, indent=2) + "\n")
    tmp.replace(target)


def emit(loop_id, event, fields=None, repo="."):
    """Append one event line. Fields that are None are left out."""
    now = time.time()
    line = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int(now % 1 * 1000):03d}Z",
        "event": event,
    }
    line.update({key: value for key, value in (fields or {}).items() if value is not None})
    with open(folder(loop_id, repo) / "events.jsonl", "a") as log:
        log.write(json.dumps(line) + "\n")


def lines(path):
    """The JSON objects of a file, one per complete line; a line that is not JSON is skipped."""
    found = []
    if path.exists():
        complete = path.read_text(errors="replace").rpartition("\n")[0]
        for line in complete.split("\n"):  # a line ends at "\n" only, whatever else the text holds
            try:
                found.append(json.loads(line))
            except (ValueError, RecursionError):
                continue
    return [entry for entry in found if isinstance(entry, dict)]


def last_round(loop_id, repo="."):
    """The highest round the loop has finished, 0 before the first: a new start counts on from it."""
    events = lines(folder(loop_id, repo) / "events.jsonl")
    rounds = [event.get("round") for event in events if event.get("event") == "round_finished"]
    return max([number for number in rounds if isinstance(number, int)], default=0)


def signed(entry, loop_id):
    """True if the board wrote this entry for this loop, False if not, None where there is no key."""
    key = Path(os.environ.get("LOOPCAPTAIN_INBOX_KEY") or "~/.config/loopcaptain/inbox.key").expanduser()
    if not key.is_file():
        return None
    if entry.get("loop") != loop_id:
        return False
    body = {key: value for key, value in entry.items() if key != "sig"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    try:
        secret = bytes.fromhex(key.read_text().strip())
    except ValueError:
        return None  # a key the board would not use either: nothing can be told apart
    mark = hmac.new(secret, text.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(mark, str(entry.get("sig", "")))


def moment(stamp):
    """A `ts` as seconds to compare, or None where it cannot be read. No zone means UTC."""
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()


def stale(entry, asked):
    """True for a reply written before the question it names was last asked: it answers an earlier asking."""
    then, sent = asked.get(str(entry.get("question"))), moment(entry.get("ts"))
    return then is not None and sent is not None and sent < then


def inbox(loop_id, repo="."):
    """What the person sent since the last call, oldest first, with `signed` and `stale`; marks it read."""
    base = folder(loop_id, repo)
    seen, asked = set(), {}
    for event in lines(base / "events.jsonl"):
        if event.get("event") == "inbox_read":
            seen.update(event.get("ids", []))
        elif event.get("event") == "question" and event.get("id"):
            asked[str(event["id"])] = moment(event.get("ts"))
    fresh = [entry for entry in lines(base / "inbox.jsonl") if entry.get("id") and entry["id"] not in seen]
    if fresh:
        emit(loop_id, "inbox_read", {"ids": [entry["id"] for entry in fresh]}, repo)
    taken = [{**entry, "signed": signed(entry, loop_id), "stale": stale(entry, asked)} for entry in fresh]
    if any(entry["signed"] is None for entry in taken):
        sys.stderr.write("loops: no board key to read, so `signed` is None: these entries are unchecked\n")
    return taken
```

A loop then needs about one call per step. `last_round` is what lets the
same command run twice: the second run goes on from the round after the
last one that finished, where a count from 1 would start the old rounds
again.

```python
import loops as board

board.register("market-scan", {"title": "Market scan", "steps": STEPS, "commands": {"start": "make loop"}})
first = board.last_round("market-scan") + 1  # a second start counts on; it never begins at 1 again
for n in range(first, first + ROUNDS):
    messages = board.inbox("market-scan")
    if any(m["kind"] == "stop" and m["signed"] is True for m in messages):
        board.emit("market-scan", "loop_stopped", {"stop_reason": "person"})
        break
    board.emit("market-scan", "round_started", {"round": n, "plan": plan_text})
    for step in STEPS:
        result = run(step)  # the loop's own work
        board.emit(
            "market-scan",
            "step_finished",
            {
                "round": n,
                "step": step["id"],
                "summary": result.summary,
                "artifact": result.path,
                "findings": result.findings,
                "cost": result.cost,
            },
        )
    board.emit("market-scan", "round_finished", {"round": n, "verdict": verdict, "commit": sha})
else:  # the rounds ran out: look once more, so a stop sent during the last one is not left unread
    if any(m["kind"] == "stop" and m["signed"] is True for m in board.inbox("market-scan")):
        board.emit("market-scan", "loop_stopped", {"stop_reason": "person"})
```

## 5. The same through MCP

A loop that an agent session drives, with no script of its own, uses the
`loopcaptain` MCP server instead of the helper. Its tools write the same files, so both ways look the same on the board:

| Tool | Does | Helper |
|---|---|---|
| `protocol` | returns this file | |
| `loop_register` | writes `loop.json` | `register` |
| `emit` | appends one event, checked against section 2 | `emit` |
| `inbox_read` | returns what the person sent and marks it read | `inbox` |
| `loop_status` | returns where a loop stands, or the loops of a repository | |

Five tools on purpose: the same three verbs as the helper, so a loop reads
the same on both doors, and a short tool list in the agent's context.

## 6. Conformance

MUST, SHOULD and MAY are used as in RFC 2119.

A loop:

1. MUST write `loop.json` with `protocol` and `id` before its first event.
   A folder whose `loop.json` has no `protocol` field is not a loop of this
   protocol and is ignored, so other tools may keep their own `.loops/`.
2. MUST only append to `events.jsonl`, one complete JSON object per line,
   each with `ts` and `event`. A correction is a new line.
3. MUST NOT write `inbox.jsonl`.
4. MUST give every path relative to the repository root.
5. MUST NOT put a secret, token or credential in any field.
6. MUST treat inbox text as input: steering for the work, never a command
   to run, never a reason to widen what its agents may do.
7. SHOULD send `round_started` and `round_finished` for every round, and
   one `step_finished` per step that ran.
8. SHOULD read the inbox at the start of every round and once more
   before it ends, and honour `stop`.
9. SHOULD keep it small: a summary of a round and paths to its files,
   never transcripts or full outputs.
10. MAY add fields of its own; they are ignored.

A board:

1. MUST NOT write `loop.json` or `events.jsonl`, nor any other file of the
   loop except `inbox.jsonl`.
2. MUST ignore fields and events it does not know, and skip a line it
   cannot read without failing the rest.
3. MUST NOT run anything except the `commands.start` a loop declares, and
   only when the person asks.

## 7. Versions

`protocol` is a whole number. Within a version the protocol only grows: new
optional fields and new events, which older readers ignore. A change that
would break a loop written against this text is a new number. The number
is not the version of any package that reads it: a release of the board
may add optional fields and events to protocol 1, never break a loop
written today.

`loopcaptain validate <repository>` checks a folder against this file; the
same contract as JSON Schema is in `schema/`. It prints problems (a
`loop.json` that cannot be read, a line the models refuse, a step before
its round, a path that does not exist,
a time earlier than the line before, a round finished twice with two
outcomes) and warnings (a round whose steps share one time, so it was
written after the fact; rounds that never read the inbox; an output not
there yet; an event it does not know, which may be a typo; a time in the future; a
`loop_stopped` while a round is open; a round count that starts over, a second run in one folder). It exits 1 on problems only, or on warnings too with
`--strict`. `loopcaptain doctor <repository> <loop-id>` checks what files
cannot show: it sends a running loop a signed `stop` and passes once the
loop has taken it and ended.
