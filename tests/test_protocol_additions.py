"""Fields protocol 1 grew from loops that faked them: each optional, each read by the fold and the board."""

from __future__ import annotations

import types
from datetime import UTC, datetime
from pathlib import Path

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
