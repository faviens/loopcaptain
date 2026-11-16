"""The example loop: written with the spec's helper, its history validates, it listens and finishes."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from loopcaptain.cli import main as cli_main
from loopcaptain.demo import SEEDED_ROUNDS, DemoError, write_demo
from loopcaptain.protocol import signing, store
from loopcaptain.protocol.doctor import examine
from loopcaptain.protocol.models import now
from loopcaptain.protocol.state import LoopState, fold
from loopcaptain.protocol.validate import validate_report
from tests.conftest import helper_source

LOOP = "loop-engineering"


def state_of(repo: Path) -> LoopState:
    events, problems = store.read_events(repo, LOOP)
    assert problems == []
    return fold(store.read_manifest(repo, LOOP), events, store.read_inbox(repo, LOOP)[0], now())


def run_loop(repo: Path, *args: str) -> None:
    command = [sys.executable, "loop.py", "--pace", "0", "--wait", "0", *args]
    subprocess.run(command, cwd=repo, check=True, timeout=60)


def test_the_demo_writes_the_helper_as_the_spec_prints_it_and_a_history_that_validates(
    tmp_path: Path,
) -> None:
    repo = write_demo(tmp_path / "demo")

    assert (repo / "loops.py").read_text() == helper_source()
    assert validate_report(repo).problems == [] and validate_report(repo).warnings == []
    state = state_of(repo)
    assert len(state.rounds) == SEEDED_ROUNDS and state.status == "idle"
    assert state.rounds[0].finished is not None and state.rounds[0].finished < now()


def test_the_example_converges_and_ends_done(tmp_path: Path) -> None:
    repo = write_demo(tmp_path / "demo")

    run_loop(repo, "--rounds", "4")

    state = state_of(repo)
    assert state.status == "done" and state.rounds[-1].stop_reason == "goal_met"
    assert state.question is None  # nobody answered in time: the loop closed its own question
    assert [r.all_metrics[0].value for r in state.rounds] == sorted(
        r.all_metrics[0].value for r in state.rounds
    )
    assert validate_report(repo).problems == []


def test_a_signed_stop_ends_it_between_rounds_and_a_forged_one_does_not(tmp_path: Path) -> None:
    repo = write_demo(tmp_path / "demo")
    signing.board_key()  # a board has run on this machine, so the loop can tell its lines apart
    forged = '{"id": "f1", "ts": "2026-11-15T00:00:00Z", "kind": "stop"}'
    store.append_line(repo / ".loops" / LOOP / "inbox.jsonl", forged)

    run_loop(repo, "--rounds", "1")
    store.append_inbox(repo, LOOP, "stop", key=signing.board_key())
    run_loop(repo, "--rounds", "1")

    state = state_of(repo)
    assert len(state.rounds) == SEEDED_ROUNDS + 1 and state.status == "stopped"
    assert state.ended is not None and state.ended.stop_reason == "person"


def test_doctor_passes_a_loop_that_listens_and_fails_one_that_does_not(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = write_demo(tmp_path / "demo")
    command = [sys.executable, "loop.py", "--pace", "0.3", "--wait", "0", "--rounds", "3"]
    running = subprocess.Popen(command, cwd=repo)
    try:
        assert cli_main(["doctor", str(repo), LOOP, "--timeout", "30"]) == 0
    finally:
        running.wait(timeout=30)
    assert "the loop took it" in capsys.readouterr().out

    deaf = examine(repo, LOOP, timeout_s=0, sleep=lambda _: None)
    assert not deaf.passed and "never took it" in deaf.lines()[1]


def test_the_demo_refuses_a_folder_it_did_not_make_and_clears_only_its_own(tmp_path: Path) -> None:
    real = tmp_path / "real-repo"
    (real / ".loops" / "mine").mkdir(parents=True)
    (real / "loop.py").write_text("# a real loop\n")

    with pytest.raises(DemoError, match="not made by the demo"):
        write_demo(real)
    assert (real / ".loops" / "mine").is_dir()

    demo = write_demo(tmp_path / "demo")
    (demo / "out" / "extra.md").write_text("old")
    write_demo(demo)
    assert not (demo / "out" / "extra.md").exists() and validate_report(demo).problems == []


def test_doctor_does_not_count_an_end_before_the_stop_was_taken(tmp_path: Path) -> None:
    repo = write_demo(tmp_path / "demo")
    clock = iter(range(100))

    def unrelated_stop(_: float) -> None:
        store.append_line(
            repo / ".loops" / LOOP / "events.jsonl",
            '{"ts": "2026-11-15T10:00:00Z", "event": "loop_stopped", "stop_reason": "round_cap"}',
        )

    checkup = examine(repo, LOOP, timeout_s=1, sleep=unrelated_stop, clock=lambda: float(next(clock)))

    assert not checkup.passed and not checkup.taken
    assert any("stays in the inbox" in line for line in checkup.lines())


def test_a_stop_sent_during_the_last_round_is_taken_before_the_loop_ends(tmp_path: Path) -> None:
    repo = write_demo(tmp_path / "demo")
    key = signing.board_key()
    command = [sys.executable, "loop.py", "--pace", "0.2", "--wait", "0", "--rounds", "1"]

    with subprocess.Popen(command, cwd=repo) as process:
        while len(state_of(repo).rounds) == SEEDED_ROUNDS:
            assert process.poll() is None, "the loop ended before its round began"
            time.sleep(0.05)
        stop = store.append_inbox(repo, LOOP, "stop", key=key)
        store.append_inbox(repo, LOOP, "reply", "Shorter rows.", key=key)
        process.wait(timeout=60)
    stopped = state_of(repo)
    run_loop(repo, "--rounds", "1")
    after = state_of(repo)

    assert stopped.status == "stopped" and not stopped.stop_requested
    assert stopped.ended is not None and stopped.rounds[-1].verdict == "continue"
    assert all(item.read for item in stopped.inbox) and stopped.inbox[0].entry.id == stop.id
    assert len(after.rounds) == SEEDED_ROUNDS + 2 and after.ended is None and after.status == "done"
    assert "Shorter rows." in (repo / "work" / "rounds" / f"{SEEDED_ROUNDS + 2}-plan.md").read_text()
