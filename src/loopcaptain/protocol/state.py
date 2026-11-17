"""Where a loop stands, folded from its event lines.

Pure: the same manifest, events and inbox always give the same state. The clock comes in as an
argument so "running or stalled" can be tested.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Literal

from loopcaptain.protocol.models import (
    AnyEvent,
    Check,
    Cost,
    FindingClosed,
    Heartbeat,
    InboxEntry,
    InboxRead,
    LoopStarted,
    LoopStopped,
    Manifest,
    Metric,
    Option,
    Question,
    QuestionClosed,
    RoundFinished,
    RoundStarted,
    StepError,
    StepFinished,
    StepStarted,
)

#: A round with no new line for this long counts as stalled, not running. A research step with
#: many agents can be quiet for a while; an hour of silence is a stopped process.
STALE_AFTER = timedelta(minutes=45)

#: How far ahead of the reader's clock a line may be stamped and still count as a sign of life.
CLOCK_SKEW = timedelta(minutes=5)

#: Stop reasons that mean a limit of the loop's own was reached.
CAP_REASONS = frozenset({"round_cap", "cost_cap", "runtime_cap"})

Status = Literal[
    "new", "running", "sleeping", "stalled", "waiting", "idle", "done", "stopped", "capped", "failed"
]
RunStatus = Literal["running", "ok", "failed", "skipped"]

#: What each status means, shown as a tooltip and in the legend.
STATUS_TEXT: dict[str, str] = {
    "new": "registered, no round yet",
    "running": "a round is under way",
    "sleeping": "between rounds, and said when it is back",
    "stalled": "a round began and has been silent for a while",
    "waiting": "waiting for your answer",
    "idle": "the last round said continue; nothing is running",
    "done": "the loop says it is done",
    "stopped": "stopped on request",
    "capped": "reached one of its caps: rounds, runtime or cost",
    "failed": "the last round failed",
}


@dataclass(frozen=True)
class FindingState:
    id: str
    text: str
    severity: str
    closed: bool = False
    resolution: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class StepRun:
    """One run of one step in one round. A fan-out step has several, told apart by `label`."""

    step: str
    label: str = ""
    status: RunStatus = "running"
    #: A gate's answer, where the step gave one: passed or not, apart from a step that broke.
    passed: bool | None = None
    started: datetime | None = None
    finished: datetime | None = None
    summary: str = ""
    artifact: str | None = None
    findings: tuple[FindingState, ...] = ()
    cost: Cost | None = None
    metrics: tuple[Metric, ...] = ()
    attempt: int | None = None
    error: StepError | None = None
    session: str | None = None
    model: str | None = None

    @property
    def open_findings(self) -> tuple[FindingState, ...]:
        return tuple(f for f in self.findings if not f.closed)

    @property
    def material_open(self) -> int:
        return sum(1 for f in self.open_findings if f.severity == "material")


@dataclass(frozen=True)
class RoundState:
    number: int
    started: datetime | None = None
    finished: datetime | None = None
    plan: str = ""
    plan_artifact: str | None = None
    mode: str = ""
    runs: tuple[StepRun, ...] = ()
    verdict: str | None = None
    stop_reason: str | None = None
    summary: str = ""
    next: str = ""
    commit: str | None = None
    verdict_artifact: str | None = None
    questions: tuple[str, ...] = ()
    #: The round's whole cost where the loop reports only the sum; it replaces the steps' costs.
    round_cost: Cost | None = None
    metrics: tuple[Metric, ...] = ()
    outcome: str | None = None
    next_at: datetime | None = None

    @property
    def running(self) -> bool:
        return self.verdict is None

    @property
    def costs(self) -> tuple[Cost, ...]:
        if self.round_cost is not None:
            return (self.round_cost,)
        return tuple(run.cost for run in self.runs if run.cost)

    @property
    def cost_usd(self) -> float:
        return finite_sum(cost.usd for cost in self.costs)

    @property
    def tokens(self) -> int:
        return sum(cost.tokens for cost in self.costs)

    @property
    def all_metrics(self) -> tuple[Metric, ...]:
        """The round's own numbers, then the last value of each that only its steps reported."""
        named = {metric.name: metric for run in self.runs for metric in run.metrics}
        named.update({metric.name: metric for metric in self.metrics})
        return tuple(named.values())

    @property
    def minutes(self) -> int | None:
        if not (self.started and self.finished):
            return None
        return max(0, round((self.finished - self.started).total_seconds() / 60))

    @property
    def findings_open(self) -> int:
        return sum(len(run.open_findings) for run in self.runs)

    @property
    def findings_closed(self) -> int:
        return sum(len(run.findings) - len(run.open_findings) for run in self.runs)

    def runs_of(self, step: str) -> tuple[StepRun, ...]:
        return tuple(run for run in self.runs if run.step == step)


@dataclass(frozen=True)
class OpenQuestion:
    text: str
    asked: datetime
    round: int | None
    blocks: bool = False
    timeout_s: int | None = None
    id: str | None = None
    options: tuple[Option, ...] = ()
    #: Not a question the loop asked but a step that failed in a way only the person can fix.
    needs_person: bool = False
    #: What the loop goes on with without an answer: an option's id, or a sentence.
    default: str = ""

    @property
    def default_text(self) -> str:
        """The default as the person reads it: the label of the option it names, else as written."""
        return next((option.label for option in self.options if option.id == self.default), self.default)

    @property
    def gives_up(self) -> datetime | None:
        """When a blocking loop stops waiting and goes on without the answer."""
        if not (self.blocks and self.timeout_s):
            return None
        try:
            return self.asked + timedelta(seconds=self.timeout_s)
        except OverflowError:
            return None  # a wait longer than the calendar: the loop never gives up


@dataclass(frozen=True)
class InboxState:
    entry: InboxEntry
    read: bool
    #: False where the signature failed: shown, but it steers nothing.
    trusted: bool = True


@dataclass(frozen=True)
class CheckState:
    kind: str
    result: str
    at: datetime
    who: str = ""
    finding: str = ""
    evidence: str | None = None
    round: int | None = None


@dataclass(frozen=True)
class ItemState:
    name: str
    checks: tuple[CheckState, ...] = ()

    def latest(self, kind: str) -> CheckState | None:
        of_kind = [check for check in self.checks if check.kind == kind]
        return of_kind[-1] if of_kind else None

    def history(self, kind: str) -> tuple[CheckState, ...]:
        return tuple(check for check in self.checks if check.kind == kind)


@dataclass(frozen=True)
class StartState:
    """The latest start of the loop's process: which start it is, its round budget, the rounds it ran."""

    number: int
    budget: int | None = None
    #: The rounds this start began, in order, and those of them that finished.
    begun: tuple[int, ...] = ()
    finished: tuple[int, ...] = ()

    @property
    def used_up(self) -> bool:
        """This start has finished as many rounds as it was given: it has ended, not gone quiet."""
        return self.budget is not None and len(self.finished) >= self.budget


@dataclass(frozen=True)
class LoopState:
    manifest: Manifest
    rounds: tuple[RoundState, ...] = ()
    status: Status = "new"
    question: OpenQuestion | None = None
    inbox: tuple[InboxState, ...] = ()
    items: tuple[ItemState, ...] = ()
    last_event: datetime | None = None
    #: Step ids that appear in events and not in the manifest, in order of first appearance.
    undeclared_steps: tuple[str, ...] = field(default=())
    #: The loop ended between rounds, after its last round finished.
    ended: LoopStopped | None = None
    #: When the loop said it would show a sign of life next.
    expected: datetime | None = None
    #: The last line in words, for a loop that went silent.
    last_line: str = ""
    #: The latest `loop_started`, for a loop that says when its process starts.
    start: StartState | None = None

    @property
    def last_round(self) -> RoundState | None:
        return self.rounds[-1] if self.rounds else None

    @property
    def cost_usd(self) -> float:
        return finite_sum(r.cost_usd for r in self.rounds)

    @property
    def tokens(self) -> int:
        return sum(r.tokens for r in self.rounds)

    @property
    def minutes(self) -> int:
        return sum(r.minutes or 0 for r in self.rounds)

    @property
    def open_findings(self) -> tuple[tuple[StepRun, FindingState], ...]:
        """What is open now: the open findings of the last round that reported any review at all.

        Reviews are fresh every round, so an earlier round's finding that is not repeated is gone.
        """
        for round_ in reversed(self.rounds):
            if any(run.findings for run in round_.runs) or not round_.running:
                return tuple((run, f) for run in round_.runs for f in run.open_findings)
        return ()

    @property
    def stop_requested(self) -> bool:
        return any(item.entry.kind == "stop" and not item.read and item.trusted for item in self.inbox)

    @property
    def check_kinds(self) -> tuple[str, ...]:
        kinds: list[str] = []
        for item in self.items:
            for check in item.checks:
                if check.kind not in kinds:
                    kinds.append(check.kind)
        return tuple(kinds)

    @property
    def step_ids(self) -> tuple[str, ...]:
        """Every step that has a row: the manifest's, then any the events name beyond it."""
        return (*(step.id for step in self.manifest.steps), *self.undeclared_steps)


def fold(
    manifest: Manifest,
    events: list[AnyEvent],
    inbox: list[InboxEntry],
    at: datetime,
    process_alive: bool = False,
    untrusted: frozenset[str] = frozenset(),
) -> LoopState:
    """The state of a loop at time `at`. `process_alive`: the board itself started it and it still runs.

    `untrusted`: ids of inbox entries whose signature failed. They are shown, but they answer no
    question and request no stop: an agent of the loop may have written them.
    """
    manifest = countable_manifest(manifest)
    rounds: dict[int, RoundState] = {}
    items: dict[str, ItemState] = {}
    read_ids: set[str] = set()
    last_question: Question | None = None
    ended: LoopStopped | None = None
    expected: datetime | None = None
    start: StartState | None = None

    for event in events:
        start = count_start(start, event)
        if isinstance(event, RoundStarted):
            ended = None
            expected = None  # a new round is its own sign of life; an older promise is spent
            if last_question is not None and last_question.blocks:
                # The loop stood still for this question and has now started a round: it went on,
                # with an answer or without one.
                last_question = None
            # A round that starts again starts clean: its earlier runs and verdict are history.
            rounds[event.round] = RoundState(
                event.round,
                started=event.when,
                plan=event.plan,
                plan_artifact=event.artifact,
                mode=event.mode,
            )
        elif isinstance(event, StepStarted | StepFinished | FindingClosed | RoundFinished):
            current = rounds.get(event.round, RoundState(event.round, started=event.when))
            rounds[event.round] = apply_to_round(current, event)
            if isinstance(event, RoundFinished):
                expected = promise(event.next_at, event.ts, at)
        elif isinstance(event, Question):
            last_question = event
            if event.round is not None and event.round in rounds:
                asked = rounds[event.round]
                rounds[event.round] = replace(asked, questions=(*asked.questions, event.text))
        elif isinstance(event, QuestionClosed):
            if last_question is not None and event.question in (None, last_question.id):
                last_question = None
        elif isinstance(event, Check):
            item = items.get(event.item, ItemState(event.item))
            check = CheckState(
                event.kind, event.result, event.when, event.who, event.finding, event.evidence, event.round
            )
            items[event.item] = replace(item, checks=(*item.checks, check))
        elif isinstance(event, InboxRead):
            read_ids.update(event.ids)
        elif isinstance(event, LoopStopped):
            ended = event
        elif isinstance(event, LoopStarted):
            ended = None  # started again: an earlier end is history
        elif isinstance(event, Heartbeat):
            expected = promise(event.next_at, event.ts, at) or expected

    ordered = tuple(rounds[n] for n in sorted(rounds))
    trusted = [entry for entry in inbox if entry.id not in untrusted]
    question = open_question(last_question, trusted, at) or needs_person(ordered, trusted)
    last_event = max((event.ts for event in events if event.ts <= at + CLOCK_SKEW), default=None)
    declared = {step.id for step in manifest.steps}
    undeclared: list[str] = []
    for round_ in ordered:
        for run in round_.runs:
            if run.step not in declared and run.step not in undeclared:
                undeclared.append(run.step)
    status = status_of(manifest, ordered, question, last_event, at, process_alive, expected)
    if status == "idle" and start is not None and start.used_up:
        status = "capped"
    if ended is not None and not process_alive and not (ordered and ordered[-1].running):
        status = ended_status(ended)
    return LoopState(
        manifest=manifest,
        rounds=ordered,
        status=status,
        question=question,
        inbox=tuple(InboxState(entry, entry.id in read_ids, entry.id not in untrusted) for entry in inbox),
        items=tuple(items.values()),
        last_event=last_event,
        undeclared_steps=tuple(undeclared),
        ended=ended,
        expected=expected,
        last_line=describe(events[-1]) if events else "",
        start=start,
    )


def count_start(start: StartState | None, event: AnyEvent) -> StartState | None:
    """The latest start after this event: a `loop_started` opens the next, a round counts in the open one."""
    if isinstance(event, LoopStarted):
        return StartState(start.number + 1 if start else 1, event.rounds)
    if start is None:
        return None
    if isinstance(event, RoundStarted) and event.round not in start.begun:
        return replace(start, begun=(*start.begun, event.round))
    if isinstance(event, RoundFinished) and event.round in start.begun and event.round not in start.finished:
        return replace(start, finished=(*start.finished, event.round))
    return start


def describe(event: AnyEvent) -> str:
    """One event as a person reads it: what, in which round, by which step."""
    parts = [event.event.replace("_", " ")]
    number = getattr(event, "round", None)
    if number:
        parts.append(f"round {number}")
    step = getattr(event, "step", None)
    label = getattr(event, "label", "")
    if step:
        parts.append(f"step {step}" + (f" ({label})" if label else ""))
    return ", ".join(parts)


#: The furthest a loop may promise its next sign of life: past this it is stalled, whatever it said.
LONGEST_PROMISE = timedelta(days=7)

#: The last moment the calendar holds: a time plus a span past it reads as this, never as an error.
END_OF_TIME = datetime.max.replace(tzinfo=UTC)


def later(moment: datetime, span: timedelta) -> datetime:
    """`moment + span`, kept within the calendar: a loop may write the year 9999."""
    try:
        return moment + span
    except OverflowError:
        return END_OF_TIME


def promise(next_at: datetime | None, written: datetime, at: datetime) -> datetime | None:
    """When the loop said it is back, capped: a `next_at` in 2099 must not hide a dead loop forever.

    A line stamped ahead of the reader's clock promises nothing, as it is no sign of life either.
    """
    if next_at is None or written > at + CLOCK_SKEW:
        return None
    return min(next_at, later(written, LONGEST_PROMISE))


#: The largest count a sum takes; a larger one has no float and counts as absent.
LARGEST_COUNT = 2**63 - 1
COUNTS = ("tokens_in", "tokens_out", "tokens_cache_read", "tokens_cache_write", "turns")


def finite_sum(figures: Iterable[float]) -> float:
    """A sum of finite figures that stays finite: one too large for a float holds the largest instead."""
    return min(sum(figures, 0.0), sys.float_info.max)


def countable_cost(cost: Cost | None) -> Cost | None:
    """A cost as the sums take it: a figure that is not finite, or no float can hold, counts as absent."""
    if cost is None:
        return None
    changes: dict[str, object] = {name: 0 for name in COUNTS if getattr(cost, name) > LARGEST_COUNT}
    if not math.isfinite(cost.usd):
        changes["usd"] = 0.0
    return cost.model_copy(update=changes) if changes else cost


def countable_metrics(metrics: list[Metric]) -> tuple[Metric, ...]:
    """The measures a page and a chart can draw: one that is not finite is absent, so is such a target."""
    return tuple(
        metric
        if metric.target is None or math.isfinite(metric.target)
        else metric.model_copy(update={"target": None})
        for metric in metrics
        if math.isfinite(metric.value)
    )


def countable_manifest(manifest: Manifest) -> Manifest:
    """The loop's caps as the board compares against them: a cost cap that is not finite is none."""
    cap = manifest.cost_cap_usd
    if cap is None or math.isfinite(cap):
        return manifest
    return manifest.model_copy(update={"cost_cap_usd": None})


def ended_status(ended: LoopStopped) -> Status:
    if ended.stop_reason in CAP_REASONS:
        return "capped"
    if ended.stop_reason == "goal_met":
        return "done"
    if ended.stop_reason in ("error", "impossible"):
        return "failed"
    return "stopped"


def needs_person(rounds: tuple[RoundState, ...], inbox: list[InboxEntry]) -> OpenQuestion | None:
    """A step of the last round that failed in a way only the person can fix, until they reply."""
    if not rounds:
        return None
    for run in reversed(rounds[-1].runs):
        if run.error is None or run.error.kind != "needs_person" or run.finished is None:
            continue
        if any(entry.kind == "reply" and entry.ts >= run.finished for entry in inbox):
            return None
        text = f"{run.step}{f' ({run.label})' if run.label else ''}: {run.error.text or run.summary}"
        return OpenQuestion(text, run.finished, rounds[-1].number, blocks=True, needs_person=True)
    return None


def apply_to_round(
    round_: RoundState, event: StepStarted | StepFinished | FindingClosed | RoundFinished
) -> RoundState:
    if isinstance(event, RoundFinished):
        return replace(
            round_,
            finished=event.when,
            verdict=event.verdict,
            stop_reason=event.stop_reason,
            summary=event.summary,
            next=event.next,
            commit=event.commit,
            verdict_artifact=event.artifact,
            round_cost=countable_cost(event.cost),
            metrics=countable_metrics(event.metrics),
            outcome=event.outcome,
            next_at=event.next_at,
        )
    if isinstance(event, FindingClosed):
        return replace(round_, runs=tuple(close_finding(run, event) for run in round_.runs))

    index = next(
        (i for i, run in enumerate(round_.runs) if run.step == event.step and run.label == event.label), None
    )
    if index is None and isinstance(event, StepFinished) and event.label:
        # Started without a label, finished with one: the same run, not a second one left running.
        index = next(
            (
                i
                for i, run in enumerate(round_.runs)
                if run.step == event.step and not run.label and run.status == "running"
            ),
            None,
        )
    if isinstance(event, StepStarted):
        started = StepRun(event.step, event.label, started=event.when)
        runs = (*round_.runs, started) if index is None else replace_at(round_.runs, index, started)
        return replace(round_, runs=runs)
    before = round_.runs[index] if index is not None else StepRun(event.step, event.label)
    finished = replace(
        before,
        label=event.label,
        status=event.status,
        passed=event.passed,
        finished=event.when,
        summary=event.summary,
        artifact=event.artifact,
        findings=tuple(FindingState(f.id, f.text, f.severity) for f in event.findings),
        cost=countable_cost(event.cost),
        metrics=countable_metrics(event.metrics),
        attempt=event.attempt,
        error=event.error,
        session=event.session,
        model=event.model,
    )
    runs = (*round_.runs, finished) if index is None else replace_at(round_.runs, index, finished)
    return replace(round_, runs=runs)


def close_finding(run: StepRun, event: FindingClosed) -> StepRun:
    """Close the finding in the step's run with the event's label, or in all its runs when none is given."""
    if run.step != event.step or (event.label and run.label != event.label):
        return run
    findings = tuple(
        replace(finding, closed=True, resolution=event.resolution, reason=event.reason)
        if finding.id == event.id
        else finding
        for finding in run.findings
    )
    return replace(run, findings=findings)


def replace_at(runs: tuple[StepRun, ...], index: int, run: StepRun) -> tuple[StepRun, ...]:
    return (*runs[:index], run, *runs[index + 1 :])


def open_question(last: Question | None, inbox: list[InboxEntry], at: datetime) -> OpenQuestion | None:
    """The loop's last question, unless the person has replied since, or the loop stopped waiting.

    A blocking question with a timeout is over once the timeout has passed: the loop went on.
    """
    if last is None:
        return None
    if any(entry.kind == "reply" and entry.ts >= last.ts for entry in inbox):
        return None
    question = OpenQuestion(
        last.text,
        last.ts,
        last.round,
        last.blocks,
        last.timeout_s,
        last.id,
        tuple(last.options),
        default=last.default,
    )
    return None if question.gives_up and question.gives_up < at else question


def status_of(
    manifest: Manifest,
    rounds: tuple[RoundState, ...],
    question: OpenQuestion | None,
    last_event: datetime | None,
    at: datetime,
    process_alive: bool,
    expected: datetime | None = None,
) -> Status:
    # A loop that stands still for the person waits, between rounds too and with its process alive.
    stands_still = question is not None and question.blocks
    if not rounds:
        if process_alive:
            return "waiting" if stands_still else "running"
        return "new"
    last = rounds[-1]
    # Silence is fine until the loop's own word for when it is back, and for a while after any line.
    promised = expected is not None and at <= later(expected, STALE_AFTER)
    if last.running:
        # A round under way waits only where the loop said it stands still, or where it has gone
        # silent with a question open. A question the loop asked in passing does not stop it.
        fresh = process_alive or promised or (last_event is not None and at - last_event <= STALE_AFTER)
        if question is not None and (question.blocks or not fresh):
            return "waiting"
        return "running" if fresh else "stalled"
    if process_alive:
        return "waiting" if stands_still else "running"
    if last.verdict == "done":
        return "done"
    if last.verdict == "failed":
        return "failed"
    if question is not None or last.verdict == "wait":
        return "waiting"
    if last.stop_reason in CAP_REASONS:
        return "capped"
    if last.verdict == "stopped":
        return "stopped"
    if cap_reached(manifest, rounds):
        return "capped"
    if expected is not None:
        return "sleeping" if promised else "stalled"
    return "idle"


def cap_reached(manifest: Manifest, rounds: tuple[RoundState, ...]) -> str:
    """Which of the loop's own limits its finished rounds have reached, in words; "" for none."""
    if manifest.round_cap is not None and len(rounds) and rounds[-1].number >= manifest.round_cap:
        return f"{manifest.round_cap} rounds"
    if (
        manifest.runtime_cap_minutes is not None
        and sum(r.minutes or 0 for r in rounds) >= manifest.runtime_cap_minutes
    ):
        return f"{manifest.runtime_cap_minutes} minutes"
    if manifest.cost_cap_usd is not None and sum(r.cost_usd for r in rounds) >= manifest.cost_cap_usd:
        return f"${manifest.cost_cap_usd:,.2f}"
    return ""


#: How many finished rounds a measure may stay flat, or open findings fail to fall, before it shows.
FLAT_ROUNDS = 3


def no_progress_signs(state: LoopState) -> list[str]:
    """The signs that a loop is going round without getting closer, in words; empty when it moves.

    The board shows them before the loop says `no_progress` itself, by the rules the guide names:
    the same material findings open two rounds running, a measure that has not moved for
    FLAT_ROUNDS rounds, open material findings that did not fall over FLAT_ROUNDS rounds.
    """
    if state.status in ("done", "stopped", "new"):
        return []
    finished = [r for r in state.rounds if not r.running and r.outcome != "discarded"]
    signs: list[str] = []

    def open_material(round_: RoundState) -> frozenset[str]:
        return frozenset(f.text for run in round_.runs for f in run.open_findings if f.severity == "material")

    if len(finished) >= 2:
        before, last = open_material(finished[-2]), open_material(finished[-1])
        if last and last == before:
            signs.append(
                f"the same {len(last)} material finding{'s' if len(last) != 1 else ''} stayed open "
                f"in rounds {finished[-2].number} and {finished[-1].number}"
            )
    recent = finished[-FLAT_ROUNDS:]
    if len(recent) == FLAT_ROUNDS:
        counts = [len(open_material(r)) for r in recent]
        if counts[0] and counts[-1] >= counts[0] and not any(s.startswith("the same") for s in signs):
            signs.append(
                f"open material findings did not fall over rounds {recent[0].number} to {recent[-1].number}"
            )
        names = {m.name for r in recent for m in r.all_metrics}
        for name in sorted(names):
            values = [next((m for m in r.all_metrics if m.name == name), None) for r in recent]
            if all(v is not None for v in values) and len({v.value for v in values if v}) == 1:
                last_metric = values[-1]
                if last_metric is not None and last_metric.met is not True:
                    signs.append(f"{name} has not moved for {FLAT_ROUNDS} rounds")
    return signs
