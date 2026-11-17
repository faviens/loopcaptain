"""The Loops protocol, version 1: what a loop writes and what the board writes back.

`LOOPS.md` beside this file is the text a loop author reads; these models are the same
contract as code. A loop needs neither: it writes JSON by hand. The board and `loopcaptain validate`
read through these models, and unknown fields are ignored so a loop may carry more than the board
shows.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    TypeAdapter,
    field_validator,
    model_validator,
)

PROTOCOL = 1
#: The folder a loop keeps in its repository, one sub-folder per loop.
FOLDER = ".loops"
MANIFEST_FILE = "loop.json"
EVENTS_FILE = "events.jsonl"
INBOX_FILE = "inbox.jsonl"

#: Loop and step ids are folder names and URL parts: lowercase, digits, dot, dash, underscore.
SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

StepKind = Literal["plan", "research", "analyse", "build", "review", "gate", "verdict", "other"]
StepStatus = Literal["ok", "failed", "skipped"]
Severity = Literal["material", "minor"]
Verdict = Literal["continue", "done", "wait", "stopped", "failed"]
#: Why a round ended the way it did, where the verdict alone does not say.
StopReason = Literal[
    "goal_met", "round_cap", "cost_cap", "runtime_cap", "person", "no_progress", "error", "impossible"
]
#: Whether a round's work was kept or thrown away (an experiment that made things worse).
Outcome = Literal["kept", "discarded"]
#: An error a retry may cure, or one only the person can.
ErrorKind = Literal["transient", "needs_person"]
#: How a question ended without a reply on the board.
QuestionEnd = Literal["answered", "superseded", "withdrawn"]
Better = Literal["higher", "lower"]
#: How a finding was settled.
Resolution = Literal["fixed", "accepted", "wontfix", "false_positive", "duplicate"]
CheckResult = Literal["pass", "partly", "fail", "blocked"]
InboxKind = Literal["reply", "stop"]


def is_slug(value: str) -> bool:
    return bool(SLUG.match(value))


def as_slug(value: str) -> str:
    if not is_slug(value):
        raise ValueError(f"{value!r} is not an id: lowercase letters, digits, '.', '-', '_', at most 64")
    return value


def aware_time(value: datetime | None) -> datetime | None:
    """A time as the readers use it: aware, UTC where the line names no zone.

    Any time the parser takes is read, the year 1 and the year 9999 included: a loop may mean
    "never" by it. The readers keep their arithmetic within the calendar (`protocol/state.py`).
    """
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def relative_path(value: str | None) -> str | None:
    """Paths in the protocol are relative to the repository root, so an export moves with its clone."""
    if value is None:
        return None
    if value.startswith(("/", "~")) or ".." in value.split("/"):
        raise ValueError(f"{value!r} must be a path inside the repository, relative to its root")
    return value


class Record(BaseModel):
    #: A number that is not finite (`NaN`, `Infinity`) is read; the readers count it as absent.
    model_config = ConfigDict(frozen=True, extra="ignore")


# ---- loop.json: what the loop is ----


class Brief(Record):
    """What the loop is for, in the person's words. `path` points to the full brief."""

    goal: str = ""
    audience: str = ""
    bar: str = ""
    path: str | None = None

    _path = field_validator("path")(relative_path)


class Step(Record):
    """One role of a round: a planner, a researcher, a reviewer, a gate.

    `after` names the steps this one waits for. Left out, the step follows the one listed before
    it, so a plain sequence needs no `after` at all.
    """

    id: str
    kind: StepKind = "other"
    name: str = ""
    purpose: str = ""
    prompt: str | None = None
    #: Plain data, shown as given: which agent runs the step (an agent's command line, a script, a
    #: person) and on which model. The protocol knows no vendor.
    backend: str | None = None
    model: str | None = None
    after: list[str] | None = None

    _id = field_validator("id")(as_slug)
    _prompt = field_validator("prompt")(relative_path)


class Workspace(Record):
    """Where the loop runs, so a person can pick it up: shown as text to copy, never run."""

    branch: str = ""
    worktree: str = ""


class StateFile(Record):
    """A file one round hands to the next: a progress note, a feature list."""

    name: str
    path: str

    _path = field_validator("path")(relative_path)


class Output(Record):
    """Something the loop makes: a deck, a dashboard, a memo."""

    name: str
    path: str

    _path = field_validator("path")(relative_path)


class Manifest(Record):
    protocol: int = PROTOCOL
    id: str
    title: str = ""
    brief: Brief = Brief()
    steps: list[Step] = Field(default_factory=list)
    #: The loop's own limits; it stops at whichever comes first. The board shows them and marks
    #: an idle loop that has reached one as capped; enforcing them is the loop's job.
    round_cap: int | None = Field(default=None, ge=1)
    runtime_cap_minutes: int | None = Field(default=None, ge=1)
    cost_cap_usd: float | None = Field(default=None, gt=0)
    pace: str = ""
    #: Commands the board may run in the repository, by name. Only "start" has a button.
    commands: dict[str, str] = Field(default_factory=dict)
    outputs: list[Output] = Field(default_factory=list)
    workspace: Workspace | None = None
    state: list[StateFile] = Field(default_factory=list)

    _id = field_validator("id")(as_slug)

    @field_validator("protocol")
    @classmethod
    def _known_protocol(cls, value: int) -> int:
        if value != PROTOCOL:
            raise ValueError(f"protocol {value} is not supported; this board reads protocol {PROTOCOL}")
        return value

    @model_validator(mode="after")
    def _steps_form_a_graph(self) -> Manifest:
        ids = [step.id for step in self.steps]
        doubles = sorted(name for name, count in Counter(ids).items() if count > 1)
        if doubles:
            raise ValueError(f"step ids must be unique: {', '.join(doubles)}")
        for step in self.steps:
            unknown = [name for name in step.after or [] if name not in ids]
            if unknown:
                raise ValueError(f"step {step.id!r} comes after unknown step(s): {', '.join(unknown)}")
        cycle = first_cycle(self.edges())
        if cycle:
            raise ValueError(f"steps wait for each other in a circle: {' -> '.join(cycle)}")
        return self

    def edges(self) -> list[tuple[str, str]]:
        """Every (before, after) pair. A step without `after` follows the step listed before it."""
        pairs: list[tuple[str, str]] = []
        for index, step in enumerate(self.steps):
            before = step.after if step.after is not None else ([self.steps[index - 1].id] if index else [])
            pairs.extend((name, step.id) for name in before)
        return pairs

    def step(self, step_id: str) -> Step | None:
        return next((step for step in self.steps if step.id == step_id), None)


def first_cycle(edges: list[tuple[str, str]]) -> list[str]:
    """A circle of steps, start repeated at the end, or [] if there is none.

    Depth first with its own stack, not recursion: a loop.json with thousands of chained steps must
    be refused or read, never crash the reader.
    """
    following: dict[str, list[str]] = {}
    for before, after in edges:
        following.setdefault(before, []).append(after)
    done: set[str] = set()
    for start in list(following):
        if start in done:
            continue
        path: list[str] = [start]
        on_path = {start}
        pending: list[list[str]] = [list(following.get(start, []))]
        while path:
            if not pending[-1]:
                finished = path.pop()
                on_path.discard(finished)
                done.add(finished)
                pending.pop()
                continue
            nxt = pending[-1].pop(0)
            if nxt in on_path:
                return [*path[path.index(nxt) :], nxt]
            if nxt not in done:
                path.append(nxt)
                on_path.add(nxt)
                pending.append(list(following.get(nxt, [])))
    return []


# ---- events.jsonl: what happened, one line each ----


class Finding(Record):
    """Something a step found wrong. `id` is unique within its step and round."""

    id: str
    text: str
    severity: Severity = "material"

    @field_validator("id", mode="before")
    @classmethod
    def _id_as_text(cls, value: object) -> object:
        return str(value) if isinstance(value, int) else value


class Cost(Record):
    """What a step or round cost. `usd` is optional: an agent on a subscription reports none.

    An infinite figure, or a count larger than a float holds, is read and counted as absent; `NaN` is
    not a cost and makes the line a problem, as it always did."""

    usd: float = Field(default=0.0, ge=0)
    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)
    tokens_cache_read: int = Field(default=0, ge=0)
    tokens_cache_write: int = Field(default=0, ge=0)
    turns: int = Field(default=0, ge=0)
    #: True where the figures are the loop's estimate, not what the agent reported.
    estimated: bool = False

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out + self.tokens_cache_read + self.tokens_cache_write


class Metric(Record):
    """A number a loop optimises, per step or round: a score, a test pass rate, a word count.

    A `value` that is not finite is read and not drawn; such a `target` counts as none."""

    name: str
    value: float
    target: float | None = None
    better: Better | None = None
    unit: str = ""

    @property
    def met(self) -> bool | None:
        if self.target is None or self.better is None:
            return None
        return self.value >= self.target if self.better == "higher" else self.value <= self.target


class StepError(Record):
    kind: ErrorKind = "transient"
    text: str = ""


class Option(Record):
    """One answer a question offers; the board draws a button for it."""

    id: str
    label: str


class Event(Record):
    """`ts` is when the line was written. `at`, optional, is when the thing really happened, for a loop
    that reports later than it works: durations are measured on `at` where it is given.

    Any year is read; a time without a zone is UTC. A number that is not finite is read and counted as
    absent."""

    ts: datetime
    at: datetime | None = None

    _times = field_validator("ts", "at")(aware_time)

    @property
    def when(self) -> datetime:
        return self.at or self.ts


class RoundStarted(Event):
    event: Literal["round_started"] = "round_started"
    round: int = Field(ge=1)
    plan: str = ""
    artifact: str | None = None

    _artifact = field_validator("artifact")(relative_path)


class StepStarted(Event):
    event: Literal["step_started"] = "step_started"
    round: int = Field(ge=1)
    step: str
    #: Tells runs of the same step apart within a round: one research agent per angle.
    label: str = ""


class StepFinished(Event):
    event: Literal["step_finished"] = "step_finished"
    round: int = Field(ge=1)
    step: str
    label: str = ""
    status: StepStatus = "ok"
    #: A gate's answer: true it let the work through, false it said no. A gate that said no ran
    #: well (`status` ok); `failed` is for a step that broke.
    passed: bool | None = None
    summary: str = ""
    artifact: str | None = None
    findings: list[Finding] = Field(default_factory=list)
    cost: Cost | None = None
    metrics: list[Metric] = Field(default_factory=list)
    #: Which try of this step in this round, from 1; with `error`, why it did not succeed.
    attempt: int | None = Field(default=None, ge=1)
    error: StepError | None = None
    #: The agent session the step ran in, to resume it by hand: shown as text, never run.
    session: str | None = None
    #: The model this run really used, where it differs from the step's in loop.json (a fallback).
    model: str | None = None

    _artifact = field_validator("artifact")(relative_path)


class FindingClosed(Event):
    event: Literal["finding_closed"] = "finding_closed"
    round: int = Field(ge=1)
    step: str
    id: str
    #: Which run of a fan-out step; left out, the finding is closed in every run of the step.
    label: str = ""
    resolution: Resolution | None = None
    reason: str = ""

    @field_validator("id", mode="before")
    @classmethod
    def _id_as_text(cls, value: object) -> object:
        return str(value) if isinstance(value, int) else value


class RoundFinished(Event):
    event: Literal["round_finished"] = "round_finished"
    round: int = Field(ge=1)
    verdict: Verdict
    stop_reason: StopReason | None = None
    summary: str = ""
    next: str = ""
    commit: str | None = None
    artifact: str | None = None
    #: The round's whole cost, for a loop that knows only the sum; step costs are then not added.
    cost: Cost | None = None
    metrics: list[Metric] = Field(default_factory=list)
    outcome: Outcome | None = None
    #: When the next round starts, for a loop that sleeps between rounds: not stalled until then.
    next_at: datetime | None = None

    _artifact = field_validator("artifact")(relative_path)
    _next_at = field_validator("next_at")(aware_time)


class LoopStarted(Event):
    """A start of the loop's process: one command, a number of rounds, then it ends.

    A loop started many times in one folder says so here, with `rounds`, what this start may run: a
    start whose rounds are used up has ended, and is not a loop that went quiet."""

    event: Literal["loop_started"] = "loop_started"
    rounds: int | None = Field(default=None, ge=1)


class LoopStopped(Event):
    """The loop ended between rounds: a stop that came after the last round finished, a cap."""

    event: Literal["loop_stopped"] = "loop_stopped"
    stop_reason: StopReason = "person"
    summary: str = ""


class Heartbeat(Event):
    """Alive and between signs: a loop that sleeps or works quietly says when to expect it next."""

    event: Literal["heartbeat"] = "heartbeat"
    text: str = ""
    next_at: datetime | None = None

    _next_at = field_validator("next_at")(aware_time)


class Question(Event):
    """The loop needs the person. Open until the person replies through the inbox."""

    event: Literal["question"] = "question"
    text: str
    round: int | None = Field(default=None, ge=1)
    #: True when the loop stands still until the answer comes, and for how long it waits at most.
    blocks: bool = False
    timeout_s: int | None = Field(default=None, ge=1)
    #: Lets a reply or a `question_closed` name this question; `options` become buttons.
    id: str | None = None
    options: list[Option] = Field(default_factory=list)


class QuestionClosed(Event):
    """The loop ends its own question: answered elsewhere, overtaken by a default, or withdrawn."""

    event: Literal["question_closed"] = "question_closed"
    #: The question's id; left out, the loop's last open question.
    question: str | None = None
    reason: QuestionEnd = "answered"
    answer: str = ""


class Check(Event):
    """One check of one item the loop evaluates or builds: a use case, a skill, a feature."""

    event: Literal["check"] = "check"
    item: str
    kind: str
    result: CheckResult
    who: str = ""
    finding: str = ""
    evidence: str | None = None
    round: int | None = Field(default=None, ge=1)

    _evidence = field_validator("evidence")(relative_path)


class InboxRead(Event):
    """The loop has taken these inbox entries, so the board can show them as read."""

    event: Literal["inbox_read"] = "inbox_read"
    ids: list[str]


EVENT_NAMES = (
    "round_started",
    "step_started",
    "step_finished",
    "finding_closed",
    "round_finished",
    "question",
    "question_closed",
    "check",
    "inbox_read",
    "loop_started",
    "loop_stopped",
    "heartbeat",
)
#: The tag of a line whose `event` this reader does not know.
OTHER = "other"


class OtherEvent(Event):
    """An event this reader does not know: one a later release of version 1 added, or a loop's own.

    It is read and skipped, never refused, so a board installed today reads a loop written
    tomorrow. It still counts as a sign of life.
    """

    event: str = Field(json_schema_extra={"not": {"enum": list(EVENT_NAMES)}})


def event_tag(line: object) -> str:
    """Which model reads a line: the one its `event` names, or `OtherEvent` for a name not known here."""
    name = line.get("event") if isinstance(line, dict) else getattr(line, "event", None)
    return name if isinstance(name, str) and name in EVENT_NAMES else OTHER


AnyEvent = Annotated[
    Annotated[RoundStarted, Tag("round_started")]
    | Annotated[StepStarted, Tag("step_started")]
    | Annotated[StepFinished, Tag("step_finished")]
    | Annotated[FindingClosed, Tag("finding_closed")]
    | Annotated[RoundFinished, Tag("round_finished")]
    | Annotated[Question, Tag("question")]
    | Annotated[QuestionClosed, Tag("question_closed")]
    | Annotated[Check, Tag("check")]
    | Annotated[InboxRead, Tag("inbox_read")]
    | Annotated[LoopStarted, Tag("loop_started")]
    | Annotated[LoopStopped, Tag("loop_stopped")]
    | Annotated[Heartbeat, Tag("heartbeat")]
    | Annotated[OtherEvent, Tag(OTHER)],
    Discriminator(event_tag),
]
EVENT: TypeAdapter[AnyEvent] = TypeAdapter(AnyEvent)


# ---- inbox.jsonl: what the person sends, written by the board ----


class InboxEntry(Record):
    id: str
    ts: datetime
    kind: InboxKind
    text: str = ""
    round: int | None = None
    #: The loop this line is for; it is signed with the rest, so a line copied elsewhere fails.
    loop: str | None = None
    #: A reply to a question with an id names it; `choice` is the id of the option picked.
    question: str | None = None
    choice: str | None = None
    #: HMAC-SHA256 the board puts on every line it writes; a line without it is not from the board.
    sig: str | None = None

    def body(self) -> dict[str, object]:
        """The line as written, for checking its `sig`."""
        return dict(json.loads(self.model_dump_json(exclude_none=True)))

    _ts = field_validator("ts")(aware_time)


def now() -> datetime:
    """The time to the millisecond, as the helper writes it: an answer in the same second as its
    question still comes after it."""
    moment = datetime.now(UTC)
    return moment.replace(microsecond=moment.microsecond // 1000 * 1000)
