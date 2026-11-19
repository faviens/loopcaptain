---
description: "Monitor and steer a Ralph loop or any shell loop around a coding agent: report each iteration with one command, read the person's stop and notes with another."
---

# Monitor a Ralph loop or any shell loop

A Ralph loop is a shell loop that hands the same prompt to a coding agent
again and again until a check passes. It needs no Python and no helper to
show up on the board: two commands do it.

1. `loopcaptain emit <loop> <event> key=value ...` appends one event.
2. `loopcaptain inbox <loop>` prints what you sent from the board since
   the last call, one line each, and marks it read.

`loopcaptain status` then says in a terminal where every watched loop
stands, and the board shows the same with its rounds, its cost and a Stop
button.

## The loop

Save this as `loop.sh` in the repository the loop works in. Set
`AGENT_CMD` to your agent's command line, one that reads a prompt on
standard input and prints its answer, and `CHECK_CMD` to the command that
says whether the work is done.

```bash
#!/usr/bin/env bash
# loop.sh: hand PROMPT.md to an agent until the check passes, and report every round.
set -euo pipefail

LOOP=ralph
AGENT_CMD=${AGENT_CMD:?set AGENT_CMD to your agent command, reading the prompt on standard input}
CHECK_CMD=${CHECK_CMD:-make test}
MAX_ROUNDS=${MAX_ROUNDS:-20}

mkdir -p ".loops/$LOOP" out
cat > ".loops/$LOOP/loop.json" <<JSON
{
  "protocol": 1,
  "id": "$LOOP",
  "title": "Ralph loop",
  "brief": {"goal": "Work through PROMPT.md until the check passes."},
  "steps": [
    {"id": "agent", "name": "Agent run"},
    {"id": "check", "name": "Check", "kind": "gate"}
  ],
  "commands": {"start": "bash loop.sh"},
  "round_cap": $MAX_ROUNDS
}
JSON

# A second start counts on from the rounds already finished.
round=$(grep -c '"round_finished"' ".loops/$LOOP/events.jsonl" 2>/dev/null || true)
round=${round:-0}

while true; do
  # What the person sent since the last round: only lines the board signed are printed.
  sent=$(loopcaptain inbox "$LOOP")
  if grep -q '^stop' <<<"$sent"; then
    loopcaptain emit "$LOOP" loop_stopped stop_reason=person summary="Stopped from the board."
    exit 0
  fi
  notes=$(grep '^reply' <<<"$sent" | cut -f2- || true)
  if [ "$round" -ge "$MAX_ROUNDS" ]; then
    loopcaptain emit "$LOOP" loop_stopped stop_reason=round_cap summary="Stopped at $MAX_ROUNDS rounds."
    exit 0
  fi

  round=$((round + 1))
  loopcaptain emit "$LOOP" round_started round="$round"

  loopcaptain emit "$LOOP" step_started round="$round" step=agent
  {
    cat PROMPT.md
    if [ -n "$notes" ]; then printf '\nFrom the person:\n%s\n' "$notes"; fi
  } | bash -c "$AGENT_CMD" > "out/round-$round.md"
  loopcaptain emit "$LOOP" step_finished round="$round" step=agent artifact="out/round-$round.md"

  if bash -c "$CHECK_CMD" > "out/check-$round.log" 2>&1; then
    loopcaptain emit "$LOOP" step_finished round="$round" step=check passed=true
    loopcaptain emit "$LOOP" round_finished round="$round" verdict=done stop_reason=goal_met \
      summary="The check passes."
    exit 0
  fi
  loopcaptain emit "$LOOP" step_finished round="$round" step=check passed=false \
    artifact="out/check-$round.log"
  loopcaptain emit "$LOOP" round_finished round="$round" verdict=continue \
    summary="The check still fails."
done
```

## Run it and watch it

```bash
AGENT_CMD='your-agent --print' bash loop.sh   # from the repository
loopcaptain watch .                           # once: put the repository on the board
loopcaptain status                            # where it stands, in a terminal
loopcaptain serve                             # the board; open the address it prints
```

On the board the loop shows each round with its two steps, the agent's
output and the check's log as files to open, and a Stop button. Stop is
taken before the next round starts. A note typed on the loop's page is
handed to the agent with the next prompt, under "From the person".

## What the two commands print

```console
$ loopcaptain inbox ralph
reply	Leave the migration alone, fix the tests first.
stop
$ loopcaptain inbox ralph --json
{"id": "...", "kind": "stop", "signed": true, "stale": false, ...}
```

Without `--json`, `inbox` prints only what a loop may act on: lines the
board signed for this loop that answer the present asking, as the kind, a
tab and the text on one line. Anything else in the file (a line an agent
wrote, a reply to a question asked earlier) is counted on standard error
and left out, so a script that reads the lines cannot take a forged stop
by mistake. `--json` prints every entry with `signed` and `stale`.

A value in `emit` is read as JSON where it parses (`round=2`,
`passed=true`) and as text where the field is text. `loopcaptain validate
.` checks what the loop wrote, and `loopcaptain doctor . ralph` sends a
stop and tells you whether the loop took it.
