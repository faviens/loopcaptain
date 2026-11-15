"""An example loop: it builds a one-page dashboard on loop engineering, round by round.

Standard library only, plus `loops.py`, the helper pasted from LOOPS.md: a loop needs nothing else
to show up on the board. No model and no network: the "agents" are small functions, so it costs
nothing and always runs the same way. Every claim, source and finding in it is invented.

    python loop.py --rounds 2      what the board's Start button runs, in this folder
"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import loops

LOOP = "loop-engineering"
HERE = Path(__file__).resolve().parent
PRACTICES = (
    ("Judge with another agent than the one that made the work", "A maker grades its own work kindly."),
    ("Start every round from a fresh context and a progress file", "Long contexts drift; files do not."),
    ("Commit once per round", "A round that made things worse can be thrown away whole."),
    ("Cap rounds, runtime and cost, and stop at the first", "A loop without a cap is a bill without one."),
    ("Stop when the same findings stay open two rounds running", "No progress is a verdict too."),
    ("Ask the person with options, not an open question", "A button is answered in seconds."),
    ("Report as it happens, never afterwards", "A round written later has invented durations."),
    ("Read the inbox at the start of every round", "A stop that is never read never stops anything."),
)
ANGLES = ("stopping", "judging", "cost")
AUDIENCES = (
    {"id": "leads", "label": "Team leads"},
    {"id": "builders", "label": "The engineers who build loops"},
)
ANSWER_WAIT_S = 90

MANIFEST = {
    "title": "A dashboard on loop engineering",
    "brief": {
        "goal": "One page that says which practices make an agent loop converge, with a source for each.",
        "audience": "A team about to run its first agent loop",
        "bar": "Every claim has a source, it reads in five minutes, and reviewers find nothing material",
        "path": "brief.md",
    },
    "steps": [
        {"id": "plan", "kind": "plan", "name": "Editor plans", "backend": "a function", "model": "none"},
        {"id": "research", "kind": "research", "name": "Researchers", "purpose": "One per angle"},
        {"id": "build", "kind": "build", "name": "Page builder", "purpose": "Writes out/dashboard.md"},
        {"id": "facts", "kind": "review", "after": ["build"], "purpose": "Every claim has a source"},
        {"id": "reader", "kind": "review", "after": ["build"], "purpose": "Reads as the audience"},
        {"id": "gate", "kind": "gate", "after": ["facts", "reader"]},
        {"id": "verdict", "kind": "verdict", "name": "Editor decides"},
    ],
    "round_cap": 6,
    "cost_cap_usd": 5,
    "pace": "a round every few seconds; asks once which audience comes first",
    "commands": {"start": "python3 loop.py --rounds 2"},
    "outputs": [{"name": "dashboard", "path": "out/dashboard.md"}],
    "state": [{"name": "progress", "path": "work/progress.md"}],
}


class Clock:
    """Now, or a time in the past for the history `seed` writes, moving on as the round does."""

    def __init__(self, start: datetime | None = None, pace_s: float = 0.0) -> None:
        self.at, self.pace_s = start, pace_s

    def tick(self, minutes: float) -> dict[str, str]:
        if self.at is None:
            time.sleep(self.pace_s)
            return {}
        self.at += timedelta(minutes=minutes)
        return {"ts": self.at.strftime("%Y-%m-%dT%H:%M:%SZ")}


def write(relative: str, text: str) -> str:
    path = HERE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return relative


def sourced_in(number: int) -> int:
    """How many claims carry a source after round `number`: the loop converges, two at a time."""
    return min(len(PRACTICES), 1 + 2 * number)


def build_page(number: int, audience: str, steering: str) -> str:
    sourced = sourced_in(number)
    rows = [
        f"| {name} | {why} | {f'invented source {chr(65 + i)}, 2026' if i < sourced else 'none yet'} |"
        for i, (name, why) in enumerate(PRACTICES)
    ]
    lines = [
        "# What makes an agent loop converge",
        "",
        f"For {audience}. Round {number}.{f' Steered: {steering}' if steering else ''}",
        "",
        "| Practice | Why | Source |",
        "|---|---|---|",
        *rows,
    ]
    return "\n".join(lines) + "\n"


def run_round(
    number: int, clock: Clock, audience: str = "a team about to run its first loop", steering: str = ""
) -> bool:
    """One round, reported as it happens. Returns True when the gate passes and the loop is done."""
    emit = loops.emit
    plan = f"Add sources to the claims that lack one; {len(PRACTICES) - sourced_in(number - 1)} to go."
    plan_file = write(f"work/rounds/{number}-plan.md", f"# Round {number}\n\n{plan}\n{steering}\n")
    emit(LOOP, "round_started", {"round": number, "plan": plan, "artifact": plan_file, **clock.tick(0)})
    emit(
        LOOP,
        "step_finished",
        {
            "round": number,
            "step": "plan",
            "artifact": plan_file,
            "cost": {"usd": 0.04, "tokens_in": 9_000, "tokens_out": 700, "estimated": True},
            **clock.tick(2),
        },
    )
    for angle in ANGLES:
        notes = write(
            f"work/rounds/{number}-research-{angle}.md", f"# {angle}\n\nInvented notes on {angle}.\n"
        )
        emit(
            LOOP,
            "step_finished",
            {
                "round": number,
                "step": "research",
                "label": angle,
                "artifact": notes,
                "summary": f"Notes on {angle}, with dated sources.",
                "cost": {
                    "usd": 0.06,
                    "tokens_in": 21_000,
                    "tokens_cache_read": 40_000,
                    "tokens_out": 1_400,
                    "estimated": True,
                },
                **clock.tick(4),
            },
        )
    page = write("out/dashboard.md", build_page(number, audience, steering))
    share = sourced_in(number) / len(PRACTICES)
    emit(
        LOOP,
        "step_finished",
        {
            "round": number,
            "step": "build",
            "artifact": page,
            "summary": f"{len(PRACTICES)} practices on one page.",
            "metrics": [
                {"name": "claims with a source", "value": round(share, 2), "target": 1.0, "better": "higher"}
            ],
            "cost": {"usd": 0.09, "tokens_in": 30_000, "tokens_out": 3_000, "estimated": True},
            **clock.tick(5),
        },
    )
    unsourced = [name for name, _ in PRACTICES[sourced_in(number) :]]
    facts = [{"id": str(i + 1), "text": f"No source for: {name}."} for i, name in enumerate(unsourced)]
    reader = [{"id": "1", "text": "The table is too long to read in five minutes."}] if number < 3 else []
    if number == 3:
        reader = [{"id": "1", "text": "Say who the page is for in the title.", "severity": "minor"}]
    for step, found in (("facts", facts), ("reader", reader)):
        review = write(
            f"work/rounds/{number}-review-{step}.md",
            "".join(f"- {f['text']}\n" for f in found) or "Nothing.\n",
        )
        emit(
            LOOP,
            "step_finished",
            {
                "round": number,
                "step": step,
                "artifact": review,
                "findings": found,
                "summary": f"{len(found)} finding(s).",
                **clock.tick(3),
            },
        )
    material = sum(1 for f in [*facts, *reader] if f.get("severity", "material") == "material")
    passed = material == 0
    emit(
        LOOP,
        "step_finished",
        {
            "round": number,
            "step": "gate",
            "status": "ok" if passed else "failed",
            "summary": "No material finding." if passed else f"{material} material finding(s) open.",
            **clock.tick(1),
        },
    )
    emit(LOOP, "step_finished", {"round": number, "step": "verdict", **clock.tick(1)})
    write("work/progress.md", f"Round {number}: {sourced_in(number)} of {len(PRACTICES)} claims sourced.\n")
    verdict = {
        "round": number,
        "verdict": "done" if passed else "continue",
        "stop_reason": "goal_met" if passed else None,
        "summary": "Every claim has a source." if passed else f"{material} material finding(s) remain.",
        "next": "" if passed else "Source the next claims.",
        "metrics": [
            {"name": "claims with a source", "value": round(share, 2), "target": 1.0, "better": "higher"}
        ],
    }
    emit(LOOP, "round_finished", {**verdict, **clock.tick(1)})
    return passed


def ask_audience(number: int, pace_s: float, wait_s: float = ANSWER_WAIT_S) -> str | None:
    """Ask once which audience comes first, with buttons; go on with a default if nobody answers.

    None means the person sent a stop while the loop waited.
    """
    loops.emit(
        LOOP,
        "question",
        {
            "id": "audience",
            "round": number,
            "blocks": True,
            "timeout_s": max(1, int(wait_s)),
            "text": "Who should the page speak to first?",
            "options": list(AUDIENCES),
        },
    )
    waited = 0.0
    while waited < wait_s:
        for message in loops.inbox(LOOP):
            if message["signed"] is False:
                continue  # not from the board: an agent or a hand wrote it, not the person
            if message["kind"] == "stop":
                return None
            if message["kind"] == "reply":
                picked = next(
                    (a["label"] for a in AUDIENCES if a["id"] == message.get("choice")), message["text"]
                )
                return picked
        time.sleep(max(pace_s, 0.5))
        waited += max(pace_s, 0.5)
    loops.emit(
        LOOP,
        "question_closed",
        {
            "question": "audience",
            "reason": "superseded",
            "answer": "No answer in time; went on for team leads.",
        },
    )
    return "Team leads"


def past_rounds() -> int:
    finished = [
        e for e in loops.lines(HERE / ".loops" / LOOP / "events.jsonl") if e.get("event") == "round_finished"
    ]
    return max((e["round"] for e in finished), default=0)


def seed(rounds: int) -> None:
    """The loop's history: its first rounds, run now with times from yesterday."""
    loops.register(LOOP, MANIFEST)
    write("brief.md", "# Brief\n\n" + MANIFEST["brief"]["goal"] + "\n")
    clock = Clock(datetime.now(UTC).replace(microsecond=0) - timedelta(days=1))
    for number in range(1, rounds + 1):
        loops.inbox(LOOP)
        run_round(number, clock)
        clock.tick(60)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rounds", type=int, default=2, help="how many rounds to run now")
    parser.add_argument("--pace", type=float, default=1.5, help="seconds between steps")
    parser.add_argument("--wait", type=float, default=ANSWER_WAIT_S, help="seconds to wait for an answer")
    parser.add_argument("--seed", type=int, metavar="N", help="write N past rounds as history, then end")
    args = parser.parse_args(argv)
    if args.seed:
        seed(args.seed)
        return 0
    loops.register(LOOP, MANIFEST)
    audience, steering = "a team about to run its first loop", ""
    for number in range(past_rounds() + 1, past_rounds() + 1 + args.rounds):
        messages = loops.inbox(LOOP)
        if any(m["kind"] == "stop" and m["signed"] is not False for m in messages):
            loops.emit(LOOP, "loop_stopped", {"stop_reason": "person", "summary": "Stopped from the board."})
            return 0
        steering = " ".join(m["text"] for m in messages if m["kind"] == "reply" and m["signed"] is not False)
        if number == 3:
            picked = ask_audience(number, args.pace, args.wait)
            if picked is None:
                loops.emit(
                    LOOP, "loop_stopped", {"stop_reason": "person", "summary": "Stopped while it asked."}
                )
                return 0
            audience = picked
        if run_round(number, Clock(pace_s=args.pace), audience, steering):
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
