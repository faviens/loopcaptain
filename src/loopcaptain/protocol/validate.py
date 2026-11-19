"""`loopcaptain validate`: check a repository's `.loops` folders against the protocol.

A problem breaks the text of LOOPS.md or makes the board show something false; a warning is a sign
that a loop is wired in a way that hides what really happens (a round written after the fact, an
inbox nobody reads). `--strict` counts warnings as problems.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from loopcaptain.protocol import store
from loopcaptain.protocol.models import (
    EVENTS_FILE,
    FOLDER,
    MANIFEST_FILE,
    AnyEvent,
    InboxEntry,
    InboxRead,
    LoopStopped,
    Manifest,
    Metric,
    OtherEvent,
    RoundFinished,
    RoundStarted,
    StepFinished,
    StepStarted,
    now,
)
from loopcaptain.protocol.state import CLOCK_SKEW, COUNTS, LARGEST_COUNT
from loopcaptain.protocol.store import StoreError


@dataclass
class Report:
    """What `validate` found, problems and warnings apart, one line each."""

    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def extend(self, prefix: str, other: Report) -> None:
        self.problems.extend(f"{prefix}{line}" for line in other.problems)
        self.warnings.extend(f"{prefix}{line}" for line in other.warnings)


def validate_repo(repo: Path) -> list[str]:
    """Every problem found, one line each; empty when the folders are sound."""
    return validate_report(repo).problems


def validate_report(repo: Path) -> Report:
    """Problems and warnings of every loop in a repository.

    Only folders whose loop.json carries the `protocol` field are loops; anything else another
    tool keeps under the same name is not this protocol's business.
    """
    folder = repo / FOLDER
    if not folder.is_dir():
        return Report(problems=[f"{repo}: no {FOLDER} folder"])
    loops = store.loop_ids(repo)
    if not loops:
        return Report(
            problems=[
                f"{FOLDER}: no loop inside "
                f"(a loop is a sub-folder whose {MANIFEST_FILE} has a protocol field)"
            ]
        )
    report = Report()
    for loop_id in loops:
        report.extend(f"{loop_id}/", validate_loop(repo, loop_id))
    return report


def validate_loop(repo: Path, loop_id: str) -> Report:
    try:
        manifest = store.read_manifest(repo, loop_id)
        events, event_problems = store.read_events(repo, loop_id)
        inbox, inbox_problems = store.read_inbox(repo, loop_id)
    except StoreError as error:
        return Report(problems=[str(error)])
    report = Report(problems=[str(problem) for problem in (*event_problems, *inbox_problems)])
    report.problems += order_problems(manifest, events)
    report.problems += missing_paths(repo, manifest, events)
    report.problems += time_problems(events)
    report.problems += verdict_problems(events)
    report.warnings += back_produced(events)
    report.warnings += missing_outputs(repo, manifest)
    report.warnings += unread_inbox(events, inbox)
    report.warnings += restarted_count(events)
    report.warnings += unknown_events(events)
    report.warnings += future_events(events, now())
    report.warnings += stop_in_a_round(events)
    report.warnings += odd_values(manifest, events)
    report.warnings += long_log(repo, loop_id)
    return Report(list(dict.fromkeys(report.problems)), list(dict.fromkeys(report.warnings)))


def long_log(repo: Path, loop_id: str) -> list[str]:
    """A log past half of what the board reads: said while there is still room to act on it."""
    try:
        size = (store.loop_dir(repo, loop_id) / EVENTS_FILE).stat().st_size
    except OSError:
        return []
    if size <= store.MAX_LOG_BYTES // 2:
        return []
    return [
        f"events.jsonl: {size // 1_000_000} MB; the board reads a log of up to "
        f"{store.MAX_LOG_BYTES // 1_000_000} MB and refuses a larger one whole. Go on under a new loop id"
    ]


def unread_inbox(events: list[AnyEvent], inbox: list[InboxEntry]) -> list[str]:
    """Entries the person sent before a round began that the loop never took: it does not listen."""
    taken = {entry_id for event in events if isinstance(event, InboxRead) for entry_id in event.ids}
    starts = [event.ts for event in events if isinstance(event, RoundStarted)]
    missed = [entry for entry in inbox if entry.id not in taken and starts and entry.ts < max(starts)]
    if not missed:
        return []
    count = f"{len(missed)} entr{'y' if len(missed) == 1 else 'ies'}"
    return [f"inbox.jsonl: {count} sent before a round began and never taken; does the loop read it?"]


def order_problems(manifest: Manifest, events: list[AnyEvent]) -> list[str]:
    declared = {step.id for step in manifest.steps}
    started: set[int] = set()
    problems: list[str] = []
    unknown: list[str] = []
    for event in events:
        if isinstance(event, RoundStarted):
            started.add(event.round)
        elif isinstance(event, RoundFinished):
            if event.round not in started:
                problems.append(f"events.jsonl: round {event.round} finished without round_started")
        elif isinstance(event, StepStarted | StepFinished):
            if event.round not in started:
                problems.append(
                    f"events.jsonl: step {event.step!r} reported for round {event.round} before it started"
                )
            if declared and event.step not in declared and event.step not in unknown:
                unknown.append(event.step)
    return problems + [f"events.jsonl: step {step!r} is not in loop.json" for step in unknown]


def missing_paths(repo: Path, manifest: Manifest, events: list[AnyEvent]) -> list[str]:
    """Paths the loop names as written that are not there: the board would link to nothing."""
    problems = [
        f"loop.json: {path} does not exist"
        for path in (manifest.brief.path, *(step.prompt for step in manifest.steps))
        if path and not (repo / path).exists()
    ]
    for event in events:
        if isinstance(event, StepFinished) and event.artifact and not (repo / event.artifact).exists():
            problems.append(
                f"events.jsonl: round {event.round} step {event.step!r}: {event.artifact} does not exist"
            )
    return problems


def missing_outputs(repo: Path, manifest: Manifest) -> list[str]:
    """Outputs may not exist before the loop is done, so a missing one is a warning."""
    return [
        f"loop.json: output {output.name!r} at {output.path} does not exist yet"
        for output in manifest.outputs
        if not (repo / output.path).exists()
    ]


def time_problems(events: list[AnyEvent]) -> list[str]:
    """Lines stamped earlier than a line before them, one problem per run of them.

    A clock that jumps back once puts every following line below the latest time until it catches
    up: that is one fault, said once with how many lines it covers, not once per line.
    """
    runs: list[tuple[int, int, AnyEvent]] = []  # first and last line of each run, and its first event
    latest: datetime | None = None
    open_run = False
    for number, event in enumerate(events, start=1):
        if latest is not None and event.ts < latest:
            if open_run:
                first, _, opening = runs[-1]
                runs[-1] = (first, number, opening)
            else:
                runs.append((number, number, event))
            open_run = True
            continue
        latest, open_run = event.ts, False
    return [time_problem(first, last, opening) for first, last, opening in runs]


def time_problem(first: int, last: int, opening: AnyEvent) -> str:
    if first == last:
        return f"events.jsonl: event {first} ({opening.event}) is earlier than the one before it"
    return (
        f"events.jsonl: events {first} to {last} ({last - first + 1} lines) "
        f"are earlier than event {first - 1} before them"
    )


def verdict_problems(events: list[AnyEvent]) -> list[str]:
    verdicts: dict[int, str] = {}
    problems = []
    for event in events:
        if isinstance(event, RoundStarted):
            verdicts.pop(event.round, None)  # a round that starts again starts clean, its verdict too
        if not isinstance(event, RoundFinished):
            continue
        earlier = verdicts.get(event.round)
        verdicts[event.round] = event.verdict
        # `wait` is a pause, not an outcome: a round that waited may finish again.
        if earlier and earlier != "wait" and earlier != event.verdict:
            problems.append(
                f"events.jsonl: round {event.round} finished twice, as {earlier} and as {event.verdict}"
            )
    return problems


def back_produced(events: list[AnyEvent]) -> list[str]:
    """A round whose start, steps and end all carry one time was written after the fact: its
    durations are invented. Steps alone may share a time honestly, where a loop stamps to the
    second and two of them end within one."""
    times: dict[int, set[datetime]] = {}
    counts: dict[int, int] = {}
    for event in events:
        if isinstance(event, RoundStarted | StepFinished | RoundFinished):
            times.setdefault(event.round, set()).add(event.when)
        if isinstance(event, StepFinished):
            counts[event.round] = counts.get(event.round, 0) + 1
    return [
        f"events.jsonl: round {number}: its start, its end and all {counts[number]} steps share one time; "
        "written after the fact?"
        for number, stamps in sorted(times.items())
        if counts.get(number, 0) > 1 and len(stamps) == 1
    ]


def restarted_count(events: list[AnyEvent]) -> list[str]:
    """A round started below one already started: a second run counting from the start in one folder."""
    highest = 0
    warnings = []
    for event in events:
        if not isinstance(event, RoundStarted):
            continue
        if event.round < highest:
            warnings.append(
                f"events.jsonl: round {event.round} started after round {highest}; "
                "a new run? give each run its own loop id"
            )
        highest = max(highest, event.round)
    return warnings


def unknown_events(events: list[AnyEvent]) -> list[str]:
    """Events this version does not know. They are skipped, as the standard asks; a typo looks the same."""
    names = list(dict.fromkeys(event.event for event in events if isinstance(event, OtherEvent)))
    return [
        f"events.jsonl: event {name!r} is not one this version knows; it is skipped (a newer one, or a typo?)"
        for name in names
    ]


def before_writing(repo: Path, loop_id: str, event: AnyEvent) -> Report:
    """What `validate` would say of this event once it is in the log, for the two doors that write on
    a loop's behalf: a problem refuses it, since a line cannot be taken back; a warning goes with it.

    Nothing here refuses more than `validate` would: an `inbox_read` of an entry this version cannot
    read is written with a warning, and a log the reader cannot read takes the line unchecked.
    """
    try:
        manifest = store.read_manifest(repo, loop_id)
        events, _ = store.read_events(repo, loop_id)
    except StoreError as error:
        return Report(warnings=[f"{error}; written without checking it against the log"])
    report = Report(problems=refusals(repo, manifest, events, event))
    if isinstance(event, InboxRead):
        sent = {entry.id for entry in store.read_inbox(repo, loop_id)[0]}
        report.warnings += [
            f"ids: {entry_id!r} is not an entry of inbox.jsonl this version can read"
            for entry_id in event.ids
            if entry_id not in sent
        ]
    return report


def refusals(repo: Path, manifest: Manifest, events: list[AnyEvent], event: AnyEvent) -> list[str]:
    """Why this event would be a problem for good once it is in the log; empty when it may be written."""
    found: list[str] = []
    started = {before.round for before in events if isinstance(before, RoundStarted)}
    if isinstance(event, StepStarted | StepFinished | RoundFinished) and event.round not in started:
        found.append(f"round {event.round} has not started: emit round_started for it first")
    if isinstance(event, StepStarted | StepFinished):
        declared = [step.id for step in manifest.steps]
        if declared and event.step not in declared:
            found.append(f"step {event.step!r} is not in loop.json, which has {', '.join(declared)}")
    if isinstance(event, StepFinished) and event.artifact and not (repo / event.artifact).exists():
        found.append(f"artifact {event.artifact} does not exist: write the file, then report it")
    if isinstance(event, RoundFinished):
        settled = set(verdict_problems(events))
        found += [line for line in verdict_problems([*events, event]) if line not in settled]
    return found


def future_events(events: list[AnyEvent], at: datetime) -> list[str]:
    """Lines stamped later than this machine's clock: they are no sign of life until their time comes."""
    ahead = [number for number, event in enumerate(events, start=1) if event.ts > at + CLOCK_SKEW]
    if not ahead:
        return []
    count = f"{len(ahead)} event{'s are' if len(ahead) != 1 else ' is'}"
    return [
        f"events.jsonl: {count} stamped in the future, from event {ahead[0]} on; is the loop's clock right?"
    ]


def stop_in_a_round(events: list[AnyEvent]) -> list[str]:
    """A `loop_stopped` while a round is open ends nothing: the round still waits for its `round_finished`."""
    open_rounds: set[int] = set()
    warnings = []
    for event in events:
        if isinstance(event, RoundStarted):
            open_rounds.add(event.round)
        elif isinstance(event, RoundFinished):
            open_rounds.discard(event.round)
        elif isinstance(event, LoopStopped) and open_rounds:
            warnings.append(
                f"events.jsonl: loop_stopped while round {max(open_rounds)} is open; "
                "finish the round first, with its verdict"
            )
    return warnings


#: Years a loop's times usually lie in. A time outside is read and counted; `validate` asks about it.
USUAL_YEARS = range(2000, 2101)


#: Beyond these a value is more likely a fault of the loop than a fact about it.
MOST_ROUNDS = 100_000
LONGEST_TEXT = 100_000
LARGEST_USD = 1_000_000
#: The fields of an event that hold free text.
TEXTS = ("summary", "text", "plan", "answer", "reason", "evidence")


def odd_values(manifest: Manifest, events: list[AnyEvent]) -> list[str]:
    """Values every reader takes but no page can show as written: a far year, a number that is not finite."""
    warnings = []
    if manifest.cost_cap_usd is not None and not math.isfinite(manifest.cost_cap_usd):
        warnings.append("loop.json: cost_cap_usd is not a finite number; the board shows no cost cap")
    for number, event in enumerate(events, start=1):
        times = [getattr(event, name, None) for name in ("ts", "at", "next_at")]
        years = sorted({moment.year for moment in times if moment and moment.year not in USUAL_YEARS})
        if years:
            named = ", ".join(str(year) for year in years)
            warnings.append(f"events.jsonl: event {number} ({event.event}) names the year {named}; meant?")
        if uncountable(event):
            warnings.append(
                f"events.jsonl: event {number} ({event.event}) has a cost or measure that is not a finite "
                "number, or too large for one; the board counts it as absent"
            )
        found = outsized(event)
        if found:
            warnings.append(f"events.jsonl: event {number} ({event.event}) has {' and '.join(found)}; meant?")
    return warnings


def outsized(event: AnyEvent) -> list[str]:
    """Values the models take and no loop means: a round number in the millions, a text of
    megabytes, a cost of millions for one line. Named in words; nothing is refused for them."""
    fields = event.__dict__  # read on every page for every line of a log: no attribute lookups
    number, cost = fields.get("round"), fields.get("cost")
    longest = max((len(text) for name in TEXTS if type(text := fields.get(name)) is str), default=0)
    found = []
    if type(number) is int and number > MOST_ROUNDS:
        found.append(f"round {number}")
    if longest > LONGEST_TEXT:
        found.append(f"a text of {longest:,} characters")
    if cost is not None and math.isfinite(cost.usd) and cost.usd > LARGEST_USD:
        found.append(f"a cost of {cost.usd:,.0f} dollars")
    return found


def uncountable(event: AnyEvent) -> bool:
    """Whether a cost or a measure of the event is NaN, infinite, or a count no float can hold."""
    cost = getattr(event, "cost", None)
    metrics: list[Metric] = getattr(event, "metrics", [])
    numbers = [cost.usd] if cost is not None else []
    numbers += [value for metric in metrics for value in (metric.value, metric.target) if value is not None]
    too_large = cost is not None and any(getattr(cost, name) > LARGEST_COUNT for name in COUNTS)
    return too_large or not all(math.isfinite(value) for value in numbers)
