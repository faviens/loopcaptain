"""Fields protocol 1 grew from loops that faked them: each optional, each read by the fold and the board."""

from __future__ import annotations

import time
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loopcaptain.board.app import create_app
from loopcaptain.board.discover import Config
from loopcaptain.board.steer import Runner
from loopcaptain.protocol import store
from loopcaptain.protocol.state import LoopState, fold
from loopcaptain.protocol.validate import validate_report

T0 = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)
HOST = "board.test"


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def line(repo: Path, event: str, **fields: object) -> None:
    store.append_line(
        repo / ".loops" / "scan" / "events.jsonl",
        store.dump({"ts": fields.pop("ts", iso(T0)), "event": event, **fields}),
    )


def state_of(repo: Path) -> LoopState:
    events, problems = store.read_events(repo, "scan")
    assert problems == []
    return fold(store.read_manifest(repo, "scan"), events, store.read_inbox(repo, "scan")[0], T0)


def page(repo: Path, tmp_path: Path, query: str = "") -> str:
    app = create_app(
        config=lambda: Config(repos=(repo,)),
        runner=Runner(tmp_path / "state"),
        allowed_hosts=frozenset({HOST}),
    )
    client = TestClient(app, base_url=f"http://{HOST}", follow_redirects=False)
    session = app.state.session
    client.cookies.set(session.cookie_name, session.cookie_value)
    response = client.get(f"/loop/{repo.name}/scan{query}")
    assert response.status_code == 200
    return response.text


def fresh_loop(repo: Path, helper: types.ModuleType) -> None:
    steps = [{"id": "work"}, {"id": "deep", "kind": "research"}, {"id": "gate", "kind": "gate"}]
    helper.register("scan", {"title": "Scan", "steps": steps}, repo)


def finished_round(repo: Path, number: int) -> None:
    line(repo, "round_started", round=number)
    line(repo, "round_finished", round=number, verdict="continue")


def test_a_start_counts_its_rounds_and_ends_capped_once_they_are_done(
    repo: Path, helper: types.ModuleType, tmp_path: Path
) -> None:
    fresh_loop(repo, helper)
    line(repo, "loop_started", rounds=2)
    finished_round(repo, 1)
    finished_round(repo, 2)
    line(repo, "loop_started", rounds=3)
    finished_round(repo, 3)

    going = state_of(repo)
    assert going.start is not None and (going.start.number, going.start.budget) == (2, 3)
    assert going.start.begun == (3,) and going.status == "idle"
    assert "start 2, rounds" in page(repo, tmp_path) and "1 of 3" in page(repo, tmp_path)

    finished_round(repo, 4)
    finished_round(repo, 5)

    assert state_of(repo).status == "capped"
    assert validate_report(repo).problems == []


def test_a_loop_that_never_says_it_started_reads_as_before(repo: Path, helper: types.ModuleType) -> None:
    fresh_loop(repo, helper)
    finished_round(repo, 1)

    state = state_of(repo)

    assert state.start is None and state.status == "idle"


def test_a_gate_that_says_no_reads_apart_from_a_step_that_broke(
    repo: Path, helper: types.ModuleType, tmp_path: Path
) -> None:
    fresh_loop(repo, helper)
    line(repo, "round_started", round=1)
    line(repo, "step_finished", round=1, step="work", status="failed", summary="The build broke.")
    line(repo, "step_finished", round=1, step="gate", passed=False, summary="Two facts lack a source.")
    picture = page(repo, tmp_path)
    line(repo, "round_started", round=2)
    line(repo, "step_finished", round=2, step="gate", passed=True)

    rounds = state_of(repo).rounds
    shown = page(repo, tmp_path, "?tab=rounds&round=1")

    assert [run.passed for run in rounds[0].runs] == [None, False] and rounds[1].runs[0].passed is True
    assert '<span class="st no"><i class="mark no"></i>said no</span>' in shown
    assert '<span class="st failed"><i class="mark failed"></i>failed</span>' in shown
    assert '<span class="cell" title="said no"><i class="mark no"></i>' in shown
    assert '<g class="node no">' in picture and "<title>gate: said no</title>" in picture
    assert '<i class="mark ok"></i>passed</span>' in page(repo, tmp_path, "?tab=rounds&round=2")


def test_a_question_says_what_the_loop_goes_on_with_and_when(
    repo: Path, helper: types.ModuleType, tmp_path: Path
) -> None:
    fresh_loop(repo, helper)
    options = [{"id": "seat", "label": "Per seat"}, {"id": "site", "label": "Per site"}]
    line(repo, "question", id="price", text="Per seat or per site?", options=options, default="seat")

    assert state_of(repo).question is not None
    assert state_of(repo).question.default_text == "Per seat"  # type: ignore[union-attr]
    assert "Until you answer, it goes on with: <b>Per seat</b>" in page(repo, tmp_path)

    asked = iso(datetime.now(UTC))  # the page reads the real clock: a timeout from T0 is long over
    line(
        repo,
        "question",
        ts=asked,
        text="Which audience?",
        blocks=True,
        timeout_s=600,
        default="The team leads.",
    )

    assert "goes on with: <b>The team leads.</b>" in page(repo, tmp_path)
    assert "Without an answer by" in page(repo, tmp_path)


def test_a_round_names_its_mode_and_what_it_leaves_out_reads_as_meant(
    repo: Path, helper: types.ModuleType, tmp_path: Path
) -> None:
    fresh_loop(repo, helper)
    line(repo, "round_started", round=1, mode="breadth")
    line(repo, "step_finished", round=1, step="work")
    line(repo, "step_finished", round=1, step="deep", status="skipped")
    picture = page(repo, tmp_path)

    shown = page(repo, tmp_path, "?tab=rounds&round=1")

    assert state_of(repo).rounds[0].mode == "breadth"
    assert "breadth round · " in shown and 'title="a breadth round"' in shown
    assert 'title="skipped, as a breadth round does"' in shown
    assert 'title="not in a breadth round"' in shown  # the gate, never reported
    assert "<title>deep: skipped, as a breadth round does</title>" in picture


def test_a_clock_that_jumps_back_once_is_one_problem_with_a_count(
    repo: Path, helper: types.ModuleType
) -> None:
    fresh_loop(repo, helper)
    line(repo, "round_started", round=1, ts="2026-11-15T10:00:00Z")
    for minute in range(10, 15):  # five lines written with a clock an hour behind
        line(repo, "heartbeat", ts=f"2026-11-15T09:{minute}:00Z")
    line(repo, "heartbeat", ts="2026-11-15T11:00:00Z")
    line(repo, "heartbeat", ts="2026-11-15T10:30:00Z")

    times = [problem for problem in validate_report(repo).problems if "earlier than" in problem]

    assert times == [
        "scan/events.jsonl: events 2 to 6 (5 lines) are earlier than event 1 before them",
        "scan/events.jsonl: event 8 (heartbeat) is earlier than the one before it",
    ]


def test_the_helper_stamps_the_time_itself_and_takes_when_it_happened_as_at(
    repo: Path, helper: types.ModuleType
) -> None:
    fresh_loop(repo, helper)

    try:
        helper.emit("scan", "heartbeat", {"ts": "2020-01-01T00:00:00Z"}, repo)
    except ValueError as error:
        refused = str(error)
    else:
        refused = ""
    with pytest.raises(ValueError, match="not a field"):
        helper.emit("scan", "heartbeat", {"at": "2020-01-01T00:00:00Z"}, repo)
    helper.emit("scan", "round_started", {"round": 1}, repo, at=T0)

    events, _ = store.read_events(repo, "scan")
    assert "pass when it happened as `at=`" in refused
    assert [event.event for event in events] == ["round_started"]
    assert events[0].at == T0 and events[0].ts > T0


def test_a_round_started_again_keeps_what_its_dead_try_spent(
    repo: Path, helper: types.ModuleType, tmp_path: Path
) -> None:
    fresh_loop(repo, helper)
    line(repo, "round_started", round=1)
    line(repo, "step_finished", round=1, step="work", cost={"usd": 2.71, "tokens_in": 100})
    line(repo, "round_started", round=1)  # the first try died; the round starts again, clean
    line(repo, "step_finished", round=1, step="work", cost={"usd": 19.39, "tokens_in": 900})
    line(repo, "round_finished", round=1, verdict="continue")

    state = state_of(repo)

    assert [run.cost.usd for run in state.rounds[0].runs if run.cost] == [19.39]
    assert round(state.cost_usd, 2) == 22.10 and state.tokens == 1000
    assert "$2.71 of it in an earlier try" in page(repo, tmp_path, "?tab=rounds&round=1")


def test_the_helper_reads_a_time_without_a_zone_as_this_machines_local_time(
    repo: Path, helper: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TZ", "Etc/GMT-2")  # two hours ahead of UTC
    time.tzset()
    fresh_loop(repo, helper)

    helper.emit("scan", "heartbeat", {}, repo, at=datetime(2026, 11, 15, 12, 0))
    monkeypatch.delenv("TZ")
    time.tzset()

    events, _ = store.read_events(repo, "scan")
    assert events[0].at == datetime(2026, 11, 15, 10, 0, tzinfo=UTC)
