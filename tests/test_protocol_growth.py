"""What protocol 1 grew after the first real loops: every field optional, every old loop still valid."""

from __future__ import annotations

import time
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

from loopcaptain.protocol import store
from loopcaptain.protocol.state import STALE_AFTER, LoopState, fold, no_progress_signs
from loopcaptain.protocol.validate import validate_repo, validate_report

T0 = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def state_at(repo: Path, at: datetime) -> LoopState:
    events, problems = store.read_events(repo, "scan")
    assert problems == []
    return fold(store.read_manifest(repo, "scan"), events, store.read_inbox(repo, "scan")[0], at)


def fresh_loop(repo: Path, helper: types.ModuleType) -> types.ModuleType:
    helper.register("scan", {"title": "Scan", "steps": [{"id": "work"}, {"id": "judge"}]}, repo)
    return helper


def line(repo: Path, event: str, **fields: object) -> None:
    store.append_line(
        repo / ".loops" / "scan" / "events.jsonl",
        store.dump({"ts": fields.pop("ts", iso(T0)), "event": event, **fields}),
    )


def test_a_round_that_knows_only_its_sum_shows_that_sum(repo: Path, helper: types.ModuleType) -> None:
    fresh_loop(repo, helper)
    line(repo, "round_started", round=1)
    line(repo, "step_finished", round=1, step="work", cost={"usd": 1.0})
    line(repo, "round_finished", round=1, verdict="continue", cost={"usd": 4.5, "tokens_in": 10})

    last = state_at(repo, T0).rounds[-1]

    assert last.cost_usd == 4.5 and last.tokens == 10


def test_cache_tokens_count_and_a_price_is_optional(repo: Path, helper: types.ModuleType) -> None:
    fresh_loop(repo, helper)
    line(repo, "round_started", round=1)
    cost = {"tokens_in": 5, "tokens_out": 5, "tokens_cache_read": 90, "turns": 3, "estimated": True}
    line(repo, "step_finished", round=1, step="work", cost=cost)

    last = state_at(repo, T0).rounds[-1]

    assert last.tokens == 100 and last.cost_usd == 0


def test_at_is_when_it_happened_and_ts_when_it_was_written(repo: Path, helper: types.ModuleType) -> None:
    fresh_loop(repo, helper)
    later = T0 + timedelta(days=1)
    line(repo, "round_started", round=1, ts=iso(later), at=iso(T0))
    line(repo, "step_finished", round=1, step="work", ts=iso(later), at=iso(T0 + timedelta(minutes=20)))
    line(repo, "step_finished", round=1, step="judge", ts=iso(later), at=iso(T0 + timedelta(minutes=30)))
    line(
        repo, "round_finished", round=1, verdict="continue", ts=iso(later), at=iso(T0 + timedelta(minutes=30))
    )

    assert state_at(repo, later).rounds[-1].minutes == 30
    assert not any("share one time" in warning for warning in validate_report(repo).warnings)


def test_a_loop_can_close_its_own_question(repo: Path, helper: types.ModuleType) -> None:
    fresh_loop(repo, helper)
    line(repo, "question", id="seats", text="Per seat?")
    assert state_at(repo, T0).question is not None

    line(repo, "question_closed", question="other", reason="superseded")
    assert state_at(repo, T0).question is not None
    line(repo, "question_closed", question="seats", reason="answered", answer="Per seat, from the thread.")
    assert state_at(repo, T0).question is None


def test_two_open_questions_are_both_kept_and_a_reply_answers_the_one_it_names(
    repo: Path, helper: types.ModuleType
) -> None:
    fresh_loop(repo, helper)
    line(repo, "question", id="seats", text="Per seat?")
    line(repo, "question", id="region", text="Which region?", ts=iso(T0 + timedelta(minutes=1)))
    later = T0 + timedelta(minutes=5)
    both = state_at(repo, later)

    answer = {"id": "a1", "ts": iso(T0 + timedelta(minutes=2)), "kind": "reply", "text": "Per seat."}
    store.append_line(repo / ".loops" / "scan" / "inbox.jsonl", store.dump({**answer, "question": "seats"}))
    one_left = state_at(repo, later)
    line(repo, "question_closed", question="region", reason="superseded")

    assert [question.id for question in both.questions] == ["seats", "region"]
    assert both.question is not None and both.question.id == "seats"  # the first is not hidden
    assert [question.id for question in one_left.questions] == ["region"]
    assert state_at(repo, later).questions == () and state_at(repo, later).question is None


def test_a_blocking_question_is_shown_before_one_asked_in_passing(
    repo: Path, helper: types.ModuleType
) -> None:
    fresh_loop(repo, helper)
    line(repo, "question", id="colour", text="Blue or green?")
    line(repo, "question", id="ship", text="Ship it?", blocks=True, ts=iso(T0 + timedelta(minutes=1)))

    state = state_at(repo, T0 + timedelta(minutes=2))

    assert state.question is not None and state.question.id == "ship" and len(state.questions) == 2


def test_a_question_with_options_keeps_them(repo: Path, helper: types.ModuleType) -> None:
    fresh_loop(repo, helper)
    options = [{"id": "a", "label": "Forty"}, {"id": "b", "label": "Both"}]
    line(repo, "question", id="size", text="Which size?", options=options, blocks=True)

    question = state_at(repo, T0).question

    assert question is not None and question.id == "size"
    assert [option.label for option in question.options] == ["Forty", "Both"]


def test_a_stop_between_rounds_does_not_rewrite_the_last_verdict(
    repo: Path, helper: types.ModuleType
) -> None:
    fresh_loop(repo, helper)
    line(repo, "round_started", round=1)
    line(repo, "round_finished", round=1, verdict="continue")
    line(repo, "loop_stopped", stop_reason="person")

    state = state_at(repo, T0)

    assert state.status == "stopped" and state.rounds[-1].verdict == "continue"
    assert validate_repo(repo) == []


def test_a_sleeping_loop_is_not_stalled_until_it_oversleeps(repo: Path, helper: types.ModuleType) -> None:
    fresh_loop(repo, helper)
    wake = T0 + timedelta(hours=6)
    line(repo, "round_started", round=1)
    line(repo, "round_finished", round=1, verdict="continue", next_at=iso(wake))

    assert state_at(repo, T0 + timedelta(hours=3)).status == "sleeping"
    assert state_at(repo, wake + STALE_AFTER + timedelta(minutes=1)).status == "stalled"


def test_a_heartbeat_keeps_a_quiet_round_running(repo: Path, helper: types.ModuleType) -> None:
    fresh_loop(repo, helper)
    line(repo, "round_started", round=1)
    line(repo, "heartbeat", text="training", next_at=iso(T0 + timedelta(hours=2)))

    assert state_at(repo, T0 + timedelta(hours=1, minutes=30)).status == "running"
    assert state_at(repo, T0 + timedelta(hours=4)).status == "stalled"


def test_an_error_that_needs_the_person_waits_for_them(repo: Path, helper: types.ModuleType) -> None:
    fresh_loop(repo, helper)
    line(repo, "round_started", round=1)
    error = {"kind": "needs_person", "text": "The API key expired."}
    line(repo, "step_finished", round=1, step="work", status="failed", attempt=3, error=error)

    state = state_at(repo, T0 + timedelta(hours=5))

    assert state.status == "waiting" and state.question is not None and state.question.needs_person
    assert "API key expired" in state.question.text
    store.append_inbox(repo, "scan", "reply", "Renewed.")
    assert state_at(repo, T0 + timedelta(hours=5)).question is None


def test_metrics_outcome_and_where_it_runs_are_kept(repo: Path, helper: types.ModuleType) -> None:
    helper.register(
        "scan",
        {
            "title": "Scan",
            "workspace": {"branch": "loop/scan", "worktree": "../scan-loop"},
            "state": [{"name": "progress", "path": "progress.md"}],
        },
        repo,
    )
    line(repo, "round_started", round=1)
    metric = {"name": "score", "value": 0.7, "target": 0.9, "better": "higher"}
    line(repo, "step_finished", round=1, step="work", metrics=[metric], session="abc-123", model="small")
    line(repo, "round_finished", round=1, verdict="continue", outcome="discarded", stop_reason="impossible")

    state = state_at(repo, T0)
    last = state.rounds[-1]

    assert state.manifest.workspace is not None and state.manifest.workspace.branch == "loop/scan"
    assert [m.name for m in last.all_metrics] == ["score"] and last.all_metrics[0].met is False
    assert last.outcome == "discarded" and last.runs[0].session == "abc-123"
    assert last.runs[0].model == "small"


def test_the_board_sees_no_progress_before_the_loop_says_so(repo: Path, helper: types.ModuleType) -> None:
    fresh_loop(repo, helper)
    finding = [{"id": "1", "text": "No source for the price."}]
    metric = [{"name": "score", "value": 0.5, "target": 0.9, "better": "higher"}]
    for number in (1, 2, 3):
        line(repo, "round_started", round=number)
        line(repo, "step_finished", round=number, step="judge", findings=finding)
        line(repo, "round_finished", round=number, verdict="continue", metrics=metric)

    signs = no_progress_signs(state_at(repo, T0))

    assert "the same 1 material finding stayed open in rounds 2 and 3" in signs
    assert "score stayed at 0.5 from round 1 to 3" in signs


def test_a_loop_that_moves_shows_no_sign(repo: Path, helper: types.ModuleType) -> None:
    fresh_loop(repo, helper)
    for number, found in ((1, 3), (2, 2), (3, 1)):
        line(repo, "round_started", round=number)
        findings = [{"id": str(i), "text": f"gap {number}-{i}"} for i in range(found)]
        line(repo, "step_finished", round=number, step="judge", findings=findings)
        line(repo, "round_finished", round=number, verdict="continue")

    assert no_progress_signs(state_at(repo, T0)) == []


def test_a_promise_is_spent_by_the_next_round_and_capped_at_a_week(
    repo: Path, helper: types.ModuleType
) -> None:
    fresh_loop(repo, helper)
    line(repo, "round_started", round=1)
    line(repo, "round_finished", round=1, verdict="continue", next_at=iso(T0 + timedelta(days=1)))
    line(repo, "round_started", round=2, ts=iso(T0 + timedelta(minutes=5)))

    assert state_at(repo, T0 + timedelta(hours=2)).status == "stalled"

    line(repo, "round_finished", round=2, verdict="continue", next_at="2099-01-01T00:00:00Z")
    assert state_at(repo, T0 + timedelta(days=3)).status == "sleeping"
    assert state_at(repo, T0 + timedelta(days=9)).status == "stalled"


def test_a_fast_honest_round_written_with_the_helper_is_not_called_back_produced(
    repo: Path, helper: types.ModuleType
) -> None:
    fresh_loop(repo, helper)
    helper.emit("scan", "round_started", {"round": 1}, repo)
    for step in ("work", "judge"):
        time.sleep(0.002)
        helper.emit("scan", "step_finished", {"round": 1, "step": step}, repo)
    helper.emit("scan", "round_finished", {"round": 1, "verdict": "done"}, repo)

    assert validate_report(repo).warnings == []


def test_steps_that_end_within_one_second_of_a_longer_round_are_not_called_back_produced(
    repo: Path, helper: types.ModuleType
) -> None:
    """A loop that stamps to the second: two quick steps share a time, the round does not."""
    fresh_loop(repo, helper)
    line(repo, "round_started", round=1)
    for step in ("work", "judge"):
        line(repo, "step_finished", round=1, step=step, ts=iso(T0 + timedelta(minutes=3)))
    line(repo, "round_finished", round=1, verdict="done", ts=iso(T0 + timedelta(minutes=4)))

    assert validate_report(repo).warnings == []


def test_a_round_count_that_starts_over_is_called_a_new_run(repo: Path, helper: types.ModuleType) -> None:
    fresh_loop(repo, helper)
    for number in (1, 2, 2):
        line(repo, "round_started", round=number)
    assert not any("own loop id" in warning for warning in validate_report(repo).warnings)

    line(repo, "round_started", round=1)

    warnings = validate_report(repo).warnings
    assert (
        "scan/events.jsonl: round 1 started after round 2; a new run? give each run its own loop id"
        in warnings
    )
