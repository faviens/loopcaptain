"""One bad line, or one bad file, never takes a reader down: it is reported and the rest reads."""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import time
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from loopcaptain.cli import main
from loopcaptain.protocol import spec_text, store
from loopcaptain.protocol.models import EVENT, EVENT_NAMES, Cost
from loopcaptain.protocol.signing import board_keys
from loopcaptain.protocol.state import LoopState, RoundState, finite_sum, fold
from loopcaptain.protocol.store import StoreError
from loopcaptain.protocol.validate import validate_repo, validate_report

NOW = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)
DEEP = "[" * 100_000 + "]" * 100_000
STANDARD_HELPER = Path(__file__).resolve().parents[1] / "standard" / "loops.py"


def fresh_loop(repo: Path, helper: types.ModuleType) -> Path:
    helper.register("scan", {"title": "Scan", "steps": [{"id": "work"}]}, repo)
    return repo / ".loops" / "scan"


def write_lines(path: Path, lines: list[str]) -> None:
    with path.open("a", encoding="utf-8") as log:
        log.write("".join(f"{line}\n" for line in lines))


def folded(repo: Path) -> LoopState:
    events, _ = store.read_events(repo, "scan")
    return fold(store.read_manifest(repo, "scan"), events, store.read_inbox(repo, "scan")[0], NOW)


#: Values the first release of version 1 read, each on the round_finished that ends a loop `done`.
#: A far year, a value that is not finite: read, counted sensibly, and only a warning in `validate`.
EXTREME_VALUES = [
    ('"next_at": "9999-12-31T00:00:00Z"', "the year 9999"),
    ('"next_at": "9999-12-31T23:59:59-23:59"', "the year 9999"),
    ('"next_at": "0001-01-01T00:00:00Z"', "the year 1;"),
    ('"at": "1970-01-01T00:00:00Z"', "the year 1970"),
    ('"metrics": [{"name": "score", "value": NaN}]', "not a finite number"),
    ('"metrics": [{"name": "score", "value": 1, "target": Infinity, "better": "higher"}]', "not a finite"),
    ('"cost": {"usd": 1e309}', "not a finite number"),
    ('"cost": {"tokens_in": 1' + "0" * 400 + "}", "too large"),
]


@pytest.mark.parametrize(("extra", "warning"), EXTREME_VALUES)
def test_a_line_the_first_release_read_is_still_read_and_the_loop_still_done(
    repo: Path, helper: types.ModuleType, extra: str, warning: str
) -> None:
    folder = fresh_loop(repo, helper)
    started = '{"ts": "2026-11-15T07:00:00Z", "event": "round_started", "round": 1}'
    finished = '{"ts": "2026-11-15T08:00:00Z", "event": "round_finished", "round": 1, "verdict": "done"'
    write_lines(folder / "events.jsonl", [started, f"{finished}, {extra}}}"])

    events, problems = store.read_events(repo, "scan")
    state = folded(repo)
    report = validate_report(repo)

    assert len(events) == 2 and problems == []
    assert state.status == "done" and state.cost_usd == 0 and state.tokens == 0
    assert state.rounds[0].all_metrics == () or state.rounds[0].all_metrics[0].target is None
    assert report.problems == [] and any(warning in line for line in report.warnings)


def test_a_far_promise_still_ends_a_week_after_its_line(repo: Path, helper: types.ModuleType) -> None:
    folder = fresh_loop(repo, helper)
    write_lines(
        folder / "events.jsonl",
        [
            '{"ts": "2026-11-15T08:00:00Z", "event": "round_started", "round": 1}',
            '{"ts": "2026-11-15T08:10:00Z", "event": "round_finished", "round": 1, "verdict": "continue",'
            ' "next_at": "9999-12-31T23:59:59Z"}',
            '{"ts": "9999-12-31T23:59:00Z", "event": "heartbeat", "next_at": "9999-12-31T23:59:59Z"}',
        ],
    )
    events, _ = store.read_events(repo, "scan")
    manifest = store.read_manifest(repo, "scan")

    assert fold(manifest, events, [], NOW).status == "sleeping"
    assert fold(manifest, events, [], NOW + timedelta(days=8)).status == "stalled"


def test_a_cost_cap_of_infinity_is_a_loop_without_a_cost_cap(repo: Path, helper: types.ModuleType) -> None:
    folder = fresh_loop(repo, helper)
    (folder / "loop.json").write_text('{"protocol": 1, "id": "scan", "cost_cap_usd": Infinity}')
    helper.emit("scan", "round_started", {"round": 1}, repo)
    helper.emit("scan", "round_finished", {"round": 1, "verdict": "continue"}, repo)

    state = folded(repo)

    assert state.status == "idle" and state.manifest.cost_cap_usd is None
    assert validate_report(repo).warnings == [
        "scan/loop.json: cost_cap_usd is not a finite number; the board shows no cost cap"
    ]


def test_a_line_nested_deeper_than_can_be_parsed_is_a_problem_and_the_rest_still_folds(
    repo: Path, helper: types.ModuleType
) -> None:
    folder = fresh_loop(repo, helper)
    helper.emit("scan", "round_started", {"round": 1}, repo)
    write_lines(
        folder / "events.jsonl", [f'{{"ts": "2026-11-15T08:00:00Z", "event": "heartbeat", "more": {DEEP}}}']
    )

    events, problems = store.read_events(repo, "scan")
    state = folded(repo)

    assert len(events) == 1 and len(problems) == 1 and "recursion limit" in problems[0].message
    assert state.status in ("running", "stalled")
    assert any("events.jsonl:2" in found and "recursion limit" in found for found in validate_repo(repo))


def test_a_time_without_a_zone_is_read_as_utc_wherever_it_stands(
    repo: Path, helper: types.ModuleType
) -> None:
    folder = fresh_loop(repo, helper)
    write_lines(
        folder / "events.jsonl",
        [
            '{"ts": "2026-11-15T08:00:00", "event": "round_started", "round": 1}',
            '{"ts": "2026-11-15T08:10:00", "event": "round_finished", "round": 1, "verdict": "continue",'
            ' "next_at": "2026-11-15T10:00:00"}',
            '{"ts": "2026-11-15T08:20:00", "event": "heartbeat", "next_at": "2026-11-15T11:00:00"}',
        ],
    )

    state = folded(repo)

    assert state.status == "sleeping" and state.expected == datetime(2026, 11, 15, 11, 0, tzinfo=UTC)


def test_a_question_that_waits_longer_than_the_calendar_never_gives_up(
    repo: Path, helper: types.ModuleType
) -> None:
    fresh_loop(repo, helper)
    helper.emit("scan", "round_started", {"round": 1}, repo)
    helper.emit("scan", "question", {"text": "Which?", "blocks": True, "timeout_s": 10**15}, repo)

    events, _ = store.read_events(repo, "scan")
    state = fold(store.read_manifest(repo, "scan"), events, [], events[-1].ts)

    assert state.status == "waiting" and state.question is not None and state.question.gives_up is None


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('{"protocol": 1, "id": "scan",}', "Invalid JSON: trailing comma"),
        ('{"protocol": 1, "id": "scan"', "Invalid JSON"),
        ("", "Invalid JSON"),
        (f'{{"protocol": 1, "id": "scan", "more": {DEEP}}}', "Invalid JSON: recursion limit"),
    ],
)
def test_a_loop_json_nobody_can_read_is_an_unreadable_loop_not_a_missing_one(
    repo: Path, helper: types.ModuleType, capsys: pytest.CaptureFixture[str], text: str, message: str
) -> None:
    folder = fresh_loop(repo, helper)
    (folder / "loop.json").write_text(text, encoding="utf-8")

    with pytest.raises(StoreError, match=message):
        store.read_manifest(repo, "scan")
    code = main(["validate", str(repo)])

    assert store.loop_ids(repo) == ["scan"]
    assert any(line.startswith("scan/loop.json: ") and message in line for line in validate_repo(repo))
    assert code == 1 and f"problem: scan/loop.json: {message}" in capsys.readouterr().out


def test_a_readable_loop_json_of_another_tool_is_still_skipped_quietly(repo: Path) -> None:
    other = repo / ".loops" / "other"
    other.mkdir(parents=True)
    (other / "loop.json").write_text('{"name": "something else"}', encoding="utf-8")
    (repo / ".loops" / "list").mkdir()
    (repo / ".loops" / "list" / "loop.json").write_text("[1, 2]", encoding="utf-8")

    assert store.loop_ids(repo) == []


def test_the_helper_skips_a_line_it_cannot_parse_and_reads_the_rest(
    repo: Path, helper: types.ModuleType
) -> None:
    folder = fresh_loop(repo, helper)
    write_lines(folder / "inbox.jsonl", [f'{{"id": "a", "kind": "reply", "more": {DEEP}}}'])
    store.append_inbox(repo, "scan", "reply", "Go on.")

    # Python 3.14's parser reads this nesting; older ones refuse it. Either way the reply is read.
    assert [entry.get("text") for entry in helper.inbox("scan", repo)][-1] == "Go on."


def test_a_text_with_other_line_breaks_stays_one_line_for_the_board_and_the_helper(
    repo: Path, helper: types.ModuleType
) -> None:
    folder = fresh_loop(repo, helper)
    text = "one\u2028two\u2029three\u0085four"
    sent = store.append_inbox(repo, "scan", "reply", text, keys=board_keys())
    store.append_line(
        folder / "events.jsonl",
        store.dump({"ts": "2026-11-15T08:00:00Z", "event": "heartbeat", "text": text}),
    )
    with (folder / "events.jsonl").open("a", encoding="utf-8") as log:
        log.write('{"ts": "2026-11-15T08:01:00Z", "event": "heartbeat"}\r\n{"ts": "2026-11-15T08:02:00Z"')

    entries, inbox_problems = store.read_inbox(repo, "scan")
    events, event_problems = store.read_events(repo, "scan")
    read_by_helper = helper.lines(folder / "events.jsonl")
    taken = helper.inbox("scan", repo)

    assert [entry.text for entry in entries] == [text] and inbox_problems == []
    assert [getattr(event, "text", None) for event in events] == [text, ""] and event_problems == []
    assert [line.get("text") for line in read_by_helper] == [text, None]
    assert [(entry["id"], entry["text"], entry["signed"]) for entry in taken] == [(sent.id, text, True)]


def test_an_event_this_version_does_not_know_is_skipped_not_refused(
    repo: Path, helper: types.ModuleType
) -> None:
    fresh_loop(repo, helper)
    helper.emit("scan", "round_started", {"round": 1}, repo)
    helper.emit("scan", "round_paused", {"round": 1, "why": "an event of a later release"}, repo)
    helper.emit("scan", "round_finished", {"round": 1, "verdict": "continue"}, repo)
    helper.emit("scan", "round_paused", {"round": 1}, repo)

    events, problems = store.read_events(repo, "scan")
    state = fold(store.read_manifest(repo, "scan"), events, [], events[-1].ts)
    report = validate_report(repo)

    assert problems == [] and [event.event for event in events][1] == "round_paused"
    assert state.status == "idle" and state.last_event == events[-1].ts and state.last_line == "round paused"
    assert report.problems == []
    assert [line for line in report.warnings if "round_paused" in line] == [
        "scan/events.jsonl: event 'round_paused' is not one this version knows; "
        "it is skipped (a newer one, or a typo?)"
    ]


def test_a_known_event_with_a_bad_field_and_a_line_without_an_event_are_still_problems(
    repo: Path, helper: types.ModuleType
) -> None:
    folder = fresh_loop(repo, helper)
    write_lines(
        folder / "events.jsonl",
        [
            '{"ts": "2026-11-15T08:00:00Z", "event": "round_finished", "round": 1, "verdict": "maybe"}',
            '{"ts": "2026-11-15T08:00:00Z"}',
            '{"event": "round_paused"}',
        ],
    )

    events, problems = store.read_events(repo, "scan")

    assert events == []
    assert [problem.message.split(":")[0] for problem in problems] == [
        "round_finished.verdict",
        "other.event",
        "other.ts",
    ]


def test_the_schema_takes_an_unknown_event_and_still_refuses_a_bad_known_one() -> None:
    schema = EVENT.json_schema()
    other = schema["$defs"]["OtherEvent"]

    assert {"$ref": "#/$defs/OtherEvent"} in schema["oneOf"]
    assert other["properties"]["event"]["not"] == {"enum": list(EVENT_NAMES)}
    assert sorted(other["required"]) == ["event", "ts"]


def test_a_round_that_was_started_again_may_end_with_another_verdict(
    repo: Path, helper: types.ModuleType
) -> None:
    fresh_loop(repo, helper)
    helper.emit("scan", "round_started", {"round": 1}, repo)
    helper.emit("scan", "round_finished", {"round": 1, "verdict": "failed"}, repo)
    helper.emit("scan", "round_started", {"round": 1}, repo)
    helper.emit("scan", "round_finished", {"round": 1, "verdict": "done"}, repo)
    assert validate_repo(repo) == []

    helper.emit("scan", "round_finished", {"round": 1, "verdict": "stopped"}, repo)

    assert validate_repo(repo) == ["scan/events.jsonl: round 1 finished twice, as done and as stopped"]


def test_the_helper_knows_the_last_finished_round_so_a_second_start_counts_on(
    repo: Path, helper: types.ModuleType
) -> None:
    fresh_loop(repo, helper)
    before = helper.last_round("scan", repo)
    for number in (1, 2):
        helper.emit("scan", "round_started", {"round": number}, repo)
        helper.emit("scan", "round_finished", {"round": number, "verdict": "continue"}, repo)
    helper.emit("scan", "round_started", {"round": 3}, repo)
    helper.emit("scan", "round_finished", {"round": "four", "verdict": "continue"}, repo)

    assert (before, helper.last_round("scan", repo)) == (0, 2)


def test_a_started_loop_that_stands_on_a_blocking_question_between_rounds_is_waiting(
    repo: Path, helper: types.ModuleType
) -> None:
    fresh_loop(repo, helper)
    manifest = store.read_manifest(repo, "scan")

    def status_now() -> str:
        events, _ = store.read_events(repo, "scan")
        inbox, _ = store.read_inbox(repo, "scan")
        return fold(manifest, events, inbox, events[-1].ts, process_alive=True).status

    helper.emit("scan", "question", {"text": "Start with which?", "blocks": True}, repo)
    before_any_round = status_now()
    helper.emit("scan", "round_started", {"round": 1}, repo)
    helper.emit("scan", "round_finished", {"round": 1, "verdict": "continue"}, repo)
    between_rounds = status_now()
    helper.emit("scan", "question", {"text": "By the way?"}, repo)
    asked_in_passing = status_now()
    helper.emit("scan", "question", {"text": "For whom?", "blocks": True}, repo)
    standing_still = status_now()
    time.sleep(0.002)
    store.append_inbox(repo, "scan", "reply", "Team leads.")

    assert (before_any_round, between_rounds, asked_in_passing) == ("waiting", "running", "running")
    assert (standing_still, status_now()) == ("waiting", "running")


def test_the_helper_says_on_standard_error_when_it_could_not_check_who_wrote_an_entry(
    repo: Path, helper: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    fresh_loop(repo, helper)
    store.append_inbox(repo, "scan", "stop")
    unchecked = helper.inbox("scan", repo)
    without_key = capsys.readouterr().err
    store.append_inbox(repo, "scan", "stop", keys=board_keys())
    store.append_inbox(repo, "scan", "stop")
    checked = helper.inbox("scan", repo)
    with_key = capsys.readouterr().err

    assert [entry["signed"] for entry in unchecked] == [None] and "unchecked" in without_key
    assert [entry["signed"] for entry in checked] == [True, False] and with_key == ""


def test_the_standard_tells_a_loop_to_act_on_what_the_board_signed_and_nothing_else() -> None:
    text = spec_text()

    assert 'm["signed"] is True' in text and "is not False" not in text
    assert "A loop SHOULD act only on entries whose `signed` is `true`" in text


def test_a_line_stamped_in_the_future_does_not_keep_a_silent_loop_running(
    repo: Path, helper: types.ModuleType
) -> None:
    folder = fresh_loop(repo, helper)
    write_lines(
        folder / "events.jsonl",
        [
            '{"ts": "2026-11-15T06:00:00Z", "event": "round_started", "round": 1}',
            '{"ts": "2026-11-15T09:03:00Z", "event": "heartbeat"}',
            '{"ts": "2026-12-24T09:00:00Z", "event": "step_started", "round": 1, "step": "work"}',
        ],
    )
    manifest = store.read_manifest(repo, "scan")
    events, _ = store.read_events(repo, "scan")

    state = fold(manifest, events, [], NOW)
    later = fold(manifest, events, [], NOW + timedelta(hours=2))

    assert (state.status, state.last_event) == ("running", datetime(2026, 11, 15, 9, 3, tzinfo=UTC))
    assert later.status == "stalled"
    assert any(
        "1 event is stamped in the future, from event 3 on" in line for line in validate_report(repo).warnings
    )


def test_validate_warns_of_a_loop_stopped_inside_an_open_round(repo: Path, helper: types.ModuleType) -> None:
    fresh_loop(repo, helper)
    helper.emit("scan", "round_started", {"round": 1}, repo)
    helper.emit("scan", "loop_stopped", {"stop_reason": "person"}, repo)
    inside = validate_report(repo).warnings
    helper.emit("scan", "round_finished", {"round": 1, "verdict": "stopped", "stop_reason": "person"}, repo)
    helper.emit("scan", "loop_stopped", {"stop_reason": "person"}, repo)

    assert inside == [
        "scan/events.jsonl: loop_stopped while round 1 is open; finish the round first, with its verdict"
    ]
    assert validate_report(repo).warnings == inside


def test_a_reply_older_than_the_question_it_names_is_handed_out_as_stale(
    repo: Path, helper: types.ModuleType
) -> None:
    fresh_loop(repo, helper)
    helper.emit("scan", "question", {"id": "audience", "text": "For whom?"}, repo)
    time.sleep(0.002)
    store.append_inbox(repo, "scan", "reply", "Team leads.", question="audience", choice="leads")
    store.append_inbox(repo, "scan", "reply", "And keep it short.")
    time.sleep(0.002)
    helper.emit("scan", "question", {"id": "audience", "text": "For whom, this time?"}, repo)
    earlier = helper.inbox("scan", repo)
    time.sleep(0.002)
    store.append_inbox(repo, "scan", "reply", "Engineers.", question="audience")
    store.append_inbox(repo, "scan", "reply", "Other.", question="never-asked")
    with (repo / ".loops" / "scan" / "inbox.jsonl").open("a") as log:
        log.write('{"id": "odd", "ts": "some time ago", "kind": "reply", "question": "audience"}\n')

    assert [(entry["text"], entry["stale"]) for entry in earlier] == [
        ("Team leads.", True),
        ("And keep it short.", False),
    ]
    assert [entry["stale"] for entry in helper.inbox("scan", repo)] == [False, False, False]


def test_the_helper_reads_a_time_without_a_zone_as_utc_whatever_the_machine_zone(tmp_path: Path) -> None:
    script = tmp_path / "check.py"
    script.write_text(
        "import loops\n"
        "asked = {'pick': loops.moment('2026-11-15T12:00:00Z')}\n"
        "print(loops.moment('2026-11-15T11:00:00') == loops.moment('2026-11-15T11:00:00Z'),"
        " loops.stale({'question': 'pick', 'ts': '2026-11-15T11:00:00'}, asked))\n",
        encoding="utf-8",
    )
    shutil.copy(STANDARD_HELPER, tmp_path / "loops.py")
    zone = {"PATH": os.environ.get("PATH", ""), "TZ": "America/New_York"}

    run = subprocess.run(
        [sys.executable, "-E", "-s", str(script)],
        env=zone,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    assert run.stdout.split() == ["True", "True"]


def test_costs_too_large_together_add_up_to_a_finite_figure() -> None:
    assert finite_sum([1e308, 1e308]) < float("inf")
    round_state = RoundState(number=1, started=datetime(2026, 11, 16, tzinfo=UTC), round_cost=Cost(usd=1e308))
    assert round_state.cost_usd == 1e308


def test_a_nan_cost_stays_a_problem_as_the_text_says() -> None:
    with pytest.raises(ValueError):
        Cost.model_validate(json.loads('{"usd": NaN}'))


def test_the_helper_names_utf8_wherever_it_opens_a_file() -> None:
    """A machine whose locale is not UTF-8 would otherwise read a reply with an umlaut as other
    text, and the signature over it would no longer hold."""
    tree = ast.parse(STANDARD_HELPER.read_text(encoding="utf-8"))
    opened = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            getattr(node.func, "id", "") == "open"
            or getattr(node.func, "attr", "") in {"read_text", "write_text"}
        )
    ]

    unnamed = [node.lineno for node in opened if "encoding" not in {keyword.arg for keyword in node.keywords}]
    assert len(opened) >= 4 and unnamed == []


def test_validate_names_values_no_loop_means_and_refuses_none(repo: Path, helper: types.ModuleType) -> None:
    helper.register("scan", {"title": "Scan", "steps": [{"id": "work"}]}, repo)
    helper.emit("scan", "round_started", {"round": 2**62}, repo)
    helper.emit("scan", "step_finished", {"round": 2**62, "step": "work", "summary": "x" * 200_000}, repo)
    helper.emit("scan", "step_finished", {"round": 2**62, "step": "work", "cost": {"usd": 5e9}}, repo)
    helper.emit("scan", "round_finished", {"round": 2**62, "verdict": "continue"}, repo)

    report = validate_report(repo)
    said = " ".join(report.warnings)

    assert report.problems == []
    assert f"round {2**62}" in said and "a text of 200,000 characters" in said
    assert "a cost of 5,000,000,000 dollars" in said


def test_a_log_is_parsed_once_per_state_of_its_file(
    repo: Path, helper: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One page reads a loop's log several times, and a reloading page again with nothing written."""
    helper.register("scan", {"title": "Scan"}, repo)
    helper.emit("scan", "round_started", {"round": 1}, repo)
    reads: list[Path] = []
    lines = store.complete_lines

    def counted(path: Path) -> list[tuple[int, str]]:
        reads.append(path)
        return lines(path)

    monkeypatch.setattr(store, "complete_lines", counted)

    first, _ = store.read_events(repo, "scan")
    second, _ = store.read_events(repo, "scan")
    second.clear()  # the list is the caller's: emptying it empties no other
    time.sleep(0.01)
    helper.emit("scan", "round_finished", {"round": 1, "verdict": "done"}, repo)
    third, _ = store.read_events(repo, "scan")
    fourth, _ = store.read_events(repo, "scan")

    assert len(reads) == 2 and len(first) == 1
    assert [event.event for event in third] == ["round_started", "round_finished"] and third == fourth


def test_a_log_rewritten_to_the_same_size_is_read_again(repo: Path, helper: types.ModuleType) -> None:
    helper.register("scan", {"title": "Scan"}, repo)
    log = repo / ".loops" / "scan" / "events.jsonl"
    log.write_text('{"ts": "2026-11-15T09:00:00Z", "event": "round_started", "round": 1}\n')
    before, _ = store.read_events(repo, "scan")
    time.sleep(0.01)

    log.write_text('{"ts": "2026-11-15T09:00:00Z", "event": "round_started", "round": 7}\n')
    after, _ = store.read_events(repo, "scan")

    assert [event.round for event in before] == [1] and [event.round for event in after] == [7]  # type: ignore[union-attr]


def test_validate_warns_of_a_log_past_half_of_what_the_board_reads(
    repo: Path, helper: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper.register("scan", {"title": "Scan"}, repo)
    helper.emit("scan", "round_started", {"round": 1}, repo)
    assert validate_report(repo).warnings == []

    monkeypatch.setattr(store, "MAX_LOG_BYTES", 100)

    assert validate_report(repo).warnings == [
        "scan/events.jsonl: 0 MB; the board reads a log of up to 0 MB and refuses a larger one whole. "
        "Go on under a new loop id"
    ]
