"""`loopcaptain validate`: check a repository's `.loops` folders against the protocol.

A problem breaks the text of LOOPS.md or makes the board show something false; a warning is a sign
that a loop is wired in a way that hides what really happens (a round written after the fact, an
inbox nobody reads). `--strict` counts warnings as problems.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from loopcaptain.protocol import store
from loopcaptain.protocol.models import (
    FOLDER,
    MANIFEST_FILE,
    AnyEvent,
    InboxEntry,
    InboxRead,
    Manifest,
    RoundFinished,
    RoundStarted,
    StepFinished,
    StepStarted,
)
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
    return Report(list(dict.fromkeys(report.problems)), list(dict.fromkeys(report.warnings)))


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
    problems = []
    latest: datetime | None = None
    for number, event in enumerate(events, start=1):
        if latest and event.ts < latest:
            problems.append(f"events.jsonl: event {number} ({event.event}) is earlier than the one before it")
        latest = max(latest, event.ts) if latest else event.ts
    return problems


def verdict_problems(events: list[AnyEvent]) -> list[str]:
    verdicts: dict[int, str] = {}
    problems = []
    for event in events:
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
    """A round whose steps all carry one time was written after the fact: its durations are invented."""
    times: dict[int, set[datetime]] = {}
    counts: dict[int, int] = {}
    for event in events:
        if isinstance(event, StepFinished):
            times.setdefault(event.round, set()).add(event.when)
            counts[event.round] = counts.get(event.round, 0) + 1
    return [
        f"events.jsonl: round {number}: all {counts[number]} steps share one time; written after the fact?"
        for number, stamps in sorted(times.items())
        if counts[number] > 1 and len(stamps) == 1
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
