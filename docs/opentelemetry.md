# Loopcaptain and OpenTelemetry

Loopcaptain sends no telemetry and takes none. The files in `.loops/` are
the interface. This page says how they map onto OpenTelemetry for anyone
who wants loops beside agent traces, and how to switch on an agent's own
telemetry next to a loop.

The mapping follows the GenAI semantic conventions, which are a draft in
development status (`open-telemetry/semantic-conventions-genai`). Names
may change; this page will follow them.

## The mapping

| Loopcaptain | OpenTelemetry |
|---|---|
| a loop (`loop.json`) | a workflow; the loop id as `gen_ai.conversation.id` |
| a round (`round_started` to `round_finished`) | a span under the workflow, `loopcaptain.round` = the number |
| a step (`step_finished`) | an agent invocation span (`invoke_agent`), named by the step id |
| `cost.tokens_in`, `cost.tokens_out` | `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` |
| a finding, a verdict, a `check` | an evaluation result event, or `loopcaptain.*` attributes |
| anything without a standard name | `loopcaptain.*`: `stop_reason`, `outcome`, `metrics`, the open findings |

`at`, where a line carries it, is the span's time; `ts` is when the line
was written.

## The agents' own telemetry

Most coding agents can export OpenTelemetry for each model call: tokens,
cost and tool calls per session. Switch it on in the agent, as its own
documentation says, and send it where you like. Put the session id in a
step's `session` field and the board shows it beside the step, so a round
on the board and the agent's traces can be joined by hand.

## Loops that run elsewhere

The board is local by design. A loop that runs on another machine, in CI
or a container, writes its `.loops/` folder there; sync that folder to a
repository the board watches (a pull, a shared folder, `rsync`), and the
board reads it like any other. The inbox flows back the same way.

## An exporter

Not built yet: a separate process that tails `events.jsonl` and sends OTLP
along the mapping above, off by default, in its own dependency group. Any
backend that takes OTLP would then work. It is finding F15 in
`.agent/FINDINGS.md`; say so there if you need it.
