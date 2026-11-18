"""Write an invented set of loops for the screenshots: several repositories, every status.

Nothing here is a real loop. Each loop is written with the helper a real loop pastes
(`standard/loops.py`), with times in the past of `now`, so the board shows what it would show for
loops that ran: one that waits for an answer, some under way, one that went silent, one that failed,
finished ones. `scripts/shots.py` photographs the result.
"""

from __future__ import annotations

import importlib.util
import json
import types
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP = "%Y-%m-%dT%H:%M:%SZ"
#: Minutes a step takes within a round, in the order the steps run.
STEP_MINUTES = {"plan": 2, "build": 9, "facts": 4, "reader": 3, "gate": 1}


@dataclass(frozen=True)
class Show:
    """One invented loop: where it lives, what it is for, and how its rounds went."""

    repo: str
    loop: str
    title: str
    goal: str
    #: Open findings each finished round left behind, oldest round first.
    left_open: tuple[int, ...]
    #: How it stands now: running, waiting, stalled, sleeping, done, failed or capped.
    ends: str
    usd_per_round: float
    #: Minutes since its last line.
    silent_for: int
    round_cap: int | None = None
    builder: str = "claude-code"
    reviewer: str = "codex"
    gaps: tuple[str, ...] = (
        "A claim has no source.",
        "A step is described twice.",
        "The summary overstates.",
    )
    measure: tuple[str, float, float] | None = None  # name, first value, target
    question: str = ""
    options: tuple[str, ...] = ()


SHOWS = (
    Show(
        "pricing-research",
        "tracker-scan",
        "Which project tracker should the team adopt?",
        "Compare six project trackers for a team of forty: fit, price and what the switch costs in year one.",
        (7, 4, 2),
        "waiting",
        4.10,
        6,
        round_cap=10,
        reviewer="gemini",
        gaps=(
            "The price of tool C is from 2024.",
            "Migration effort is asserted, not estimated.",
            "No source for the uptime figure.",
            "Two tools are compared on different plans.",
        ),
        question="Two tools tie on fit. Weigh price or migration effort higher?",
        options=("Price", "Migration effort"),
    ),
    Show(
        "checkout-service",
        "coverage",
        "Raise test coverage of the payment module",
        "Bring line coverage of the payment module to 85 percent without touching behaviour.",
        (5, 5, 3, 2, 2, 1),
        "running",
        1.85,
        2,
        round_cap=15,
        builder="codex",
        reviewer="claude-code",
        gaps=(
            "A test asserts nothing.",
            "The refund path is still uncovered.",
            "A mock hides the real client.",
        ),
        measure=("line coverage", 0.61, 0.85),
    ),
    Show(
        "support-handbook",
        "rewrite",
        "Rewrite the support handbook",
        "One handbook a new support agent reads in week one: how we answer, where things are, whom to ask.",
        (6, 4, 2),
        "running",
        2.40,
        4,
        round_cap=8,
        gaps=(
            "The escalation path names a team that no longer exists.",
            "Chapter 3 repeats chapter 1.",
            "No example for a refund.",
        ),
    ),
    Show(
        "checkout-service",
        "client-migration",
        "Move the payment client to the new API",
        "Replace every call to the old payment client; the contract tests stay green.",
        (4, 3),
        "stalled",
        3.20,
        138,
        round_cap=12,
        builder="gemini",
        gaps=(
            "Retries are not idempotent.",
            "A timeout is hard-coded.",
            "The error mapping loses the cause.",
        ),
    ),
    Show(
        "data-pipeline",
        "schema-drift",
        "Find and fix schema drift in the nightly load",
        "Every table of the nightly load matches its declared schema, or the difference is written down.",
        (3, 3, 3),
        "failed",
        2.75,
        310,
        round_cap=6,
        builder="script",
        gaps=(
            "The orders table has an undeclared column.",
            "A date is loaded as text.",
            "No check for empty partitions.",
        ),
    ),
    Show(
        "pricing-research",
        "weekly-digest",
        "Weekly digest of competitor price changes",
        "Every Monday: what changed in list prices, with the page it was read from.",
        (2, 1, 0, 1, 0, 0, 0, 0),
        "sleeping",
        0.90,
        95,
        reviewer="gemini",
        gaps=("A price is quoted without its date.", "One vendor's page did not load."),
    ),
    Show(
        "support-handbook",
        "translations",
        "Translate the handbook into three languages",
        "The handbook in German, French and Italian, checked by a reader of each.",
        (9, 5, 3, 1, 0),
        "done",
        3.60,
        1_500,
        round_cap=8,
        builder="gemini",
        gaps=(
            "A term is translated two ways.",
            "The French glossary is missing.",
            "A link points to the English page.",
        ),
    ),
    Show(
        "data-pipeline",
        "quality-report",
        "Nightly data quality report",
        "One page each morning: which loads ran, which checks failed, what changed since yesterday.",
        (4, 3, 2, 2, 1, 1),
        "capped",
        1.30,
        2_900,
        round_cap=6,
        builder="script",
        gaps=("The report does not say which run it describes.", "Late rows are counted twice."),
    ),
)


def helper() -> types.ModuleType:
    """The helper a real loop pastes, loaded from the standard."""
    spec = importlib.util.spec_from_file_location("pasted_loops", ROOT / "standard" / "loops.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("standard/loops.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def steps_of(show: Show) -> list[dict[str, object]]:
    return [
        {
            "id": "plan",
            "kind": "plan",
            "name": "Planner",
            "backend": show.builder,
            "purpose": "What this round changes",
        },
        {"id": "build", "kind": "build", "name": "Builder", "backend": show.builder, "purpose": "Does it"},
        {"id": "facts", "kind": "review", "name": "Fact check", "backend": show.reviewer, "after": ["build"]},
        {"id": "reader", "kind": "review", "name": "Reader", "backend": show.reviewer, "after": ["build"]},
        {
            "id": "gate",
            "kind": "gate",
            "name": "Gate",
            "backend": "script",
            "purpose": "No material finding left",
        },
    ]


def effort(number: int) -> float:
    """Rounds do not cost the same: a factor between 0.8 and 1.25 that repeats every four rounds."""
    return (1.25, 0.9, 1.05, 0.8)[number % 4]


def findings(show: Show, count: int, offset: int) -> list[dict[str, str]]:
    return [{"id": str(n + 1), "text": show.gaps[(n + offset) % len(show.gaps)]} for n in range(count)]


def write_loop(show: Show, base: Path, now: datetime, loops: types.ModuleType) -> None:
    """Write one loop's folder: its finished rounds, then the state it stands in now."""
    repo = base / show.repo
    repo.mkdir(parents=True, exist_ok=True)
    manifest = {
        "title": show.title,
        "brief": {"goal": show.goal, "bar": "No material finding from either reviewer."},
        "steps": steps_of(show),
        "round_cap": show.round_cap,
    }
    loops.register(show.loop, {key: value for key, value in manifest.items() if value is not None}, repo)
    round_minutes = sum(STEP_MINUTES.values()) + 2
    open_round = show.ends in ("running", "waiting", "stalled")
    ahead = 3 * open_round + (show.ends == "waiting")
    clock = now - timedelta(minutes=show.silent_for + round_minutes * len(show.left_open) + ahead)

    def emit(event: str, fields: dict[str, object], minutes: int) -> None:
        nonlocal clock
        clock += timedelta(minutes=minutes)
        # Lines written as if at their time, which the helper refuses: a showcase invents its past.
        line = {"ts": clock.strftime(STAMP), "event": event, **fields}
        with (repo / ".loops" / show.loop / "events.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(line) + "\n")

    def work(number: int) -> None:
        emit("round_started", {"round": number, "plan": f"Close what round {number - 1} left open."}, 1)
        cost = {
            "usd": round(show.usd_per_round * 0.2 * effort(number), 2),
            "tokens_in": 14_000,
            "tokens_out": 1_200,
        }
        emit("step_finished", {"round": number, "step": "plan", "cost": cost}, STEP_MINUTES["plan"])

    last = len(show.left_open)
    for number, left in enumerate(show.left_open, start=1):
        work(number)
        built: dict[str, object] = {
            "round": number,
            "step": "build",
            "summary": "Changed what the plan named.",
            "cost": {
                "usd": round(show.usd_per_round * 0.55 * effort(number), 2),
                "tokens_in": 62_000,
                "tokens_out": 7_400,
            },
        }
        if show.measure:
            name, first, target = show.measure
            value = first + (target - first) * number / (last + 2)
            built["metrics"] = [
                {"name": name, "value": round(value, 2), "target": target, "better": "higher"}
            ]
        emit("step_finished", built, STEP_MINUTES["build"])
        for step, share in (("facts", left - left // 3), ("reader", left // 3)):
            found = findings(show, share, number + (step == "reader"))
            review = {
                "round": number,
                "step": step,
                "findings": found,
                "summary": f"{len(found)} finding(s).",
            }
            review["cost"] = {
                "usd": round(show.usd_per_round * 0.125, 2),
                "tokens_in": 21_000,
                "tokens_out": 900,
            }
            emit("step_finished", review, STEP_MINUTES[step])
        passed = left == 0
        gate = {"round": number, "step": "gate", "status": "ok" if passed else "failed"}
        emit("step_finished", gate, STEP_MINUTES["gate"])
        verdict: dict[str, object] = {"round": number, "verdict": "continue", "summary": f"{left} open."}
        if number == last and show.ends == "done":
            verdict.update(verdict="done", stop_reason="goal_met", summary="Both reviewers found nothing.")
        if number == last and show.ends == "failed":
            verdict.update(
                verdict="failed", stop_reason="error", summary="The load could not be read: access refused."
            )
        if number == last and show.ends == "capped":
            verdict.update(verdict="stopped", stop_reason="round_cap", summary="The round cap is reached.")
        if number == last and show.ends == "sleeping":
            verdict["next_at"] = (now + timedelta(hours=18)).strftime(STAMP)
        emit("round_finished", verdict, 1)
    if open_round:
        work(last + 1)
    if show.ends == "waiting":
        options = [{"id": option.lower().replace(" ", "-"), "label": option} for option in show.options]
        emit("question", {"round": last + 1, "text": show.question, "blocks": True, "options": options}, 1)


def write_showcase(base: Path, now: datetime) -> list[Path]:
    """Write every invented loop under `base` and return the repositories, in the order first used."""
    loops = helper()
    for show in SHOWS:
        write_loop(show, base, now, loops)
    return [base / name for name in dict.fromkeys(show.repo for show in SHOWS)]
