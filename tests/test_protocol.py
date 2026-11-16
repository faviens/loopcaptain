from __future__ import annotations

import json
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from loopcaptain.cli import main, write_schemas
from loopcaptain.protocol import store
from loopcaptain.protocol.models import Manifest, Question, Step
from loopcaptain.protocol.state import STALE_AFTER, fold
from loopcaptain.protocol.validate import validate_repo

NOW = datetime(2026, 11, 14, 21, 0, tzinfo=UTC)


def state_of(repo: Path, at: datetime | None = None, process_alive: bool = False):  # type: ignore[no-untyped-def]
    manifest = store.read_manifest(repo, "scan")
    events, problems = store.read_events(repo, "scan")
    inbox, _ = store.read_inbox(repo, "scan")
    assert problems == []
    last = max(event.ts for event in events)
    return fold(manifest, events, inbox, at or last, process_alive)


def test_steps_without_after_form_a_sequence_and_after_overrides_it() -> None:
    manifest = Manifest(
        id="x", steps=[Step(id="a"), Step(id="b"), Step(id="c", after=["a"]), Step(id="d", after=[])]
    )

    assert manifest.edges() == [("a", "b"), ("a", "c")]


@pytest.mark.parametrize(
    ("steps", "message"),
    [
        ([{"id": "a"}, {"id": "a"}], "unique"),
        ([{"id": "a", "after": ["nope"]}], "unknown"),
        ([{"id": "a", "after": ["b"]}, {"id": "b", "after": ["a"]}], "circle"),
        ([{"id": "Not A Slug"}], "not an id"),
    ],
)
def test_manifest_refuses_a_broken_graph(steps: list[dict[str, object]], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Manifest.model_validate({"id": "x", "steps": steps})


@pytest.mark.parametrize("path", ["/etc/passwd", "../other/file.md", "~/notes.md"])
def test_paths_must_stay_inside_the_repository(path: str) -> None:
    with pytest.raises(ValidationError, match="inside the repository"):
        Manifest.model_validate({"id": "x", "brief": {"path": path}})


def test_a_newer_protocol_is_refused_with_its_number() -> None:
    with pytest.raises(ValidationError, match="protocol 2 is not supported"):
        Manifest.model_validate({"id": "x", "protocol": 2})


def test_the_pasted_helper_writes_a_folder_that_validates(scan: Path) -> None:
    assert validate_repo(scan) == []


def test_fold_gives_rounds_runs_findings_and_cost(scan: Path) -> None:
    state = state_of(scan)

    first, second = state.rounds
    assert first.verdict == "continue" and first.commit == "abc1234"
    assert [(run.step, run.label, run.status) for run in first.runs] == [
        ("plan", "", "ok"),
        ("research", "pricing", "ok"),
        ("research", "vendors", "failed"),
        ("facts", "", "ok"),
    ]
    assert first.cost_usd == pytest.approx(0.75)
    assert (first.findings_open, first.findings_closed) == (1, 1)
    assert second.running and second.runs[0].status == "running"
    assert state.cost_usd == pytest.approx(0.75)


def test_open_findings_are_those_of_the_last_reviewed_round(scan: Path) -> None:
    state = state_of(scan)

    assert [(run.step, finding.text) for run, finding in state.open_findings] == [
        ("facts", "No source for 40 percent.")
    ]


def test_status_runs_then_stalls_when_a_round_goes_silent(scan: Path) -> None:
    last = state_of(scan).last_event
    assert last is not None

    assert state_of(scan, last + timedelta(minutes=1)).status == "running"
    assert state_of(scan, last + STALE_AFTER + timedelta(minutes=1)).status == "stalled"
    assert state_of(scan, last + STALE_AFTER + timedelta(minutes=1), process_alive=True).status == "running"


def test_a_blocking_question_waits_until_the_person_replies(scan: Path, helper: types.ModuleType) -> None:
    helper.emit("scan", "question", {"round": 2, "text": "Per seat or per site?", "blocks": True}, scan)
    waiting = state_of(scan)

    store.append_inbox(scan, "scan", "reply", "Per seat.", 2)
    answered = state_of(scan, NOW + timedelta(days=3650))

    assert waiting.status == "waiting" and waiting.question is not None
    assert waiting.question.text == "Per seat or per site?"
    assert answered.question is None and answered.status == "stalled"


def test_a_question_asked_in_passing_does_not_stop_a_round_that_goes_on(
    scan: Path, helper: types.ModuleType
) -> None:
    helper.emit("scan", "question", {"round": 2, "text": "Per seat or per site?"}, scan)
    last = state_of(scan).last_event
    assert last is not None

    going = state_of(scan, last + timedelta(minutes=1))
    silent = state_of(scan, last + STALE_AFTER + timedelta(minutes=1))

    assert going.status == "running" and going.question is not None
    assert silent.status == "waiting"


def test_a_blocking_question_is_over_once_its_timeout_has_passed(
    scan: Path, helper: types.ModuleType
) -> None:
    helper.emit("scan", "question", {"round": 2, "text": "Which?", "blocks": True, "timeout_s": 60}, scan)
    asked = state_of(scan).last_event
    assert asked is not None

    assert state_of(scan, asked + timedelta(seconds=30)).status == "waiting"
    assert state_of(scan, asked + timedelta(seconds=90)).question is None


def test_a_blocking_question_is_over_once_the_loop_starts_another_round(
    scan: Path, helper: types.ModuleType
) -> None:
    helper.emit("scan", "question", {"round": 2, "text": "Which?", "blocks": True}, scan)
    helper.emit("scan", "round_finished", {"round": 2, "verdict": "continue"}, scan)
    helper.emit("scan", "round_started", {"round": 3}, scan)

    state = state_of(scan)

    assert state.question is None and state.status == "running"


def test_a_round_that_starts_again_starts_clean(scan: Path, helper: types.ModuleType) -> None:
    helper.emit("scan", "round_started", {"round": 1, "plan": "Again."}, scan)

    first = state_of(scan).rounds[0]

    assert first.running and first.runs == () and first.plan == "Again."


def test_closing_a_finding_with_a_label_leaves_the_other_runs_open(
    scan: Path, helper: types.ModuleType
) -> None:
    for label in ("a", "b"):
        helper.emit(
            "scan",
            "step_finished",
            {"round": 2, "step": "facts", "label": label, "findings": [{"id": 1, "text": f"Gap {label}."}]},
            scan,
        )

    helper.emit("scan", "finding_closed", {"round": 2, "step": "facts", "id": 1, "label": "a"}, scan)
    one_left = [finding.text for _, finding in state_of(scan).open_findings]
    helper.emit("scan", "finding_closed", {"round": 2, "step": "facts", "id": 1}, scan)

    assert one_left == ["Gap b."]
    assert state_of(scan).open_findings == ()


def test_a_step_started_without_a_label_and_finished_with_one_is_one_run(
    scan: Path, helper: types.ModuleType
) -> None:
    helper.emit("scan", "step_started", {"round": 2, "step": "research"}, scan)
    helper.emit("scan", "step_finished", {"round": 2, "step": "research", "label": "pricing"}, scan)

    runs = state_of(scan).rounds[1].runs_of("research")

    assert [(run.label, run.status) for run in runs] == [("pricing", "ok")]


def test_the_helper_and_the_board_skip_a_half_written_or_broken_line(
    scan: Path, helper: types.ModuleType
) -> None:
    store.append_inbox(scan, "scan", "reply", "Go on.")
    folder = scan / ".loops" / "scan"
    with (folder / "inbox.jsonl").open("a") as box:
        box.write('not json\n{"id": "half", "kind": "re')
    with (folder / "events.jsonl").open("ab") as log:
        log.write(b"\xff\xfe broken bytes\n")

    taken = helper.inbox("scan", scan)
    events, problems = store.read_events(scan, "scan")

    assert [entry["text"] for entry in taken] == ["Go on."]
    assert len(problems) == 1 and events[-1].event == "inbox_read"


def test_the_helper_hands_out_each_inbox_entry_once_and_marks_it_read(
    scan: Path, helper: types.ModuleType
) -> None:
    store.append_inbox(scan, "scan", "reply", "Go on.")
    store.append_inbox(scan, "scan", "stop")
    assert state_of(scan).stop_requested

    first = helper.inbox("scan", scan)
    second = helper.inbox("scan", scan)

    assert [entry["kind"] for entry in first] == ["reply", "stop"]
    assert second == []
    state = state_of(scan)
    assert all(item.read for item in state.inbox) and not state.stop_requested


@pytest.mark.parametrize(
    ("verdict", "cap", "status"),
    [
        ("done", 5, "done"),
        ("failed", 5, "failed"),
        ("stopped", 5, "stopped"),
        ("continue", 5, "idle"),
        ("continue", 2, "capped"),
    ],
)
def test_status_after_the_last_round(
    scan: Path, helper: types.ModuleType, verdict: str, cap: int, status: str
) -> None:
    helper.register("scan", {"title": "Market scan", "round_cap": cap}, scan)
    helper.emit("scan", "round_finished", {"round": 2, "verdict": verdict}, scan)

    assert state_of(scan, NOW + timedelta(days=3650)).status == status


def test_checks_fold_into_items_with_the_latest_per_kind(scan: Path, helper: types.ModuleType) -> None:
    helper.emit("scan", "check", {"item": "Tool A", "kind": "desk research", "result": "partly"}, scan)
    helper.emit(
        "scan", "check", {"item": "Tool A", "kind": "desk research", "result": "pass", "who": "facts"}, scan
    )
    helper.emit("scan", "check", {"item": "Tool B", "kind": "own trial", "result": "fail"}, scan)

    state = state_of(scan)

    assert state.check_kinds == ("desk research", "own trial")
    tool_a = state.items[0]
    latest = tool_a.latest("desk research")
    assert latest is not None and latest.result == "pass" and len(tool_a.history("desk research")) == 2
    assert tool_a.latest("own trial") is None


def test_a_bad_line_is_reported_and_the_rest_still_reads(scan: Path) -> None:
    events = scan / ".loops" / "scan" / "events.jsonl"
    with events.open("a") as log:
        log.write(
            '{"ts": "2026-11-14T21:00:00Z", "event": "round_finished", "round": 2, "verdict": "maybe"}\n'
        )
        log.write("not json\n")
        log.write(
            '{"ts": "2026-11-14T21:00:00Z", "event": "round_started", "round": 3'
        )  # still being written

    read, problems = store.read_events(scan, "scan")

    assert len(read) == 9
    assert [problem.line for problem in problems] == [10, 11]
    assert any("events.jsonl:10" in line for line in validate_repo(scan))


def test_validate_names_steps_and_rounds_the_manifest_does_not_know(
    scan: Path, helper: types.ModuleType
) -> None:
    helper.emit("scan", "step_finished", {"round": 7, "step": "mystery"}, scan)

    problems = validate_repo(scan)

    assert "scan/events.jsonl: step 'mystery' is not in loop.json" in problems
    assert any("round 7 before it started" in line for line in problems)


def test_emit_command_appends_a_valid_line_and_refuses_an_invalid_one(
    scan: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ok = main(
        [
            "emit",
            "scan",
            "round_finished",
            "round=2",
            "verdict=done",
            "summary=All closed.",
            "--repo",
            str(scan),
        ]
    )
    bad = main(["emit", "scan", "round_finished", "round=2", "verdict=perhaps", "--repo", str(scan)])

    assert (ok, bad) == (0, 1)
    assert "verdict" in capsys.readouterr().err
    assert state_of(scan, NOW + timedelta(days=3650)).status == "done"


def test_inbox_is_refused_for_a_loop_that_does_not_exist(repo: Path) -> None:
    with pytest.raises(store.StoreError, match="no loop"):
        store.append_inbox(repo, "ghost", "reply", "hello")
    with pytest.raises(store.StoreError, match="not a loop id"):
        store.append_inbox(repo, "../escape", "reply", "hello")


def test_schema_files_are_written(tmp_path: Path) -> None:
    written = write_schemas(tmp_path / "schema")

    assert [path.name for path in written] == ["loop.schema.json", "event.schema.json", "inbox.schema.json"]
    assert "steps" in json.loads(written[0].read_text())["properties"]


STANDARD = Path(__file__).parents[1] / "standard"
TEMPLATES = sorted((STANDARD / "templates").glob("*.loop.json"))


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda path: path.name)
def test_the_loop_templates_to_copy_are_valid_manifests(template: Path) -> None:
    manifest = Manifest.model_validate_json(template.read_text())

    assert len(TEMPLATES) == 3
    assert manifest.id == template.name.removesuffix(".loop.json")
    assert {step.kind for step in manifest.steps} >= {"build", "review", "verdict"}


def test_a_blocking_question_says_until_when_the_loop_waits(scan: Path, helper: types.ModuleType) -> None:
    helper.emit("scan", "question", {"round": 2, "text": "Which?", "blocks": True, "timeout_s": 600}, scan)

    question = state_of(scan).question

    assert question is not None and question.blocks
    assert question.gives_up == question.asked + timedelta(seconds=600)


@pytest.mark.parametrize(
    ("caps", "status"),
    [
        ({"runtime_cap_minutes": 1}, "idle"),
        ({"runtime_cap_minutes": 0}, "error"),
        ({"cost_cap_usd": 0.75}, "capped"),
        ({"cost_cap_usd": 5}, "idle"),
    ],
)
def test_runtime_and_cost_caps_mark_an_idle_loop_as_capped(
    scan: Path, helper: types.ModuleType, caps: dict[str, float], status: str
) -> None:
    helper.register("scan", {"title": "Market scan", **caps}, scan)
    helper.emit("scan", "round_finished", {"round": 2, "verdict": "continue"}, scan)

    if status == "error":
        with pytest.raises(store.StoreError, match="runtime_cap_minutes"):
            store.read_manifest(scan, "scan")
    else:
        assert state_of(scan, NOW + timedelta(days=3650)).status == status


def test_the_helper_file_to_copy_is_the_one_the_spec_prints() -> None:
    from tests.conftest import helper_source

    assert (STANDARD / "loops.py").read_text() == helper_source()


def test_the_published_schema_is_current(tmp_path: Path) -> None:
    for fresh in write_schemas(tmp_path):
        assert (STANDARD / "schema" / fresh.name).read_text() == fresh.read_text(), "run `make schema`"


def test_a_folder_of_another_tool_under_the_same_name_is_not_a_loop(scan: Path) -> None:
    other = scan / ".loops" / "someone-elses"
    other.mkdir()
    (other / "loop.json").write_text('{"name": "not ours", "steps": 3}')
    (scan / ".loops" / "notes").mkdir()

    assert store.loop_ids(scan) == ["scan"]
    assert validate_repo(scan) == []


@pytest.mark.parametrize(
    ("fields", "status"),
    [
        ({"verdict": "wait", "stop_reason": "person"}, "waiting"),
        ({"verdict": "stopped", "stop_reason": "cost_cap"}, "capped"),
        ({"verdict": "stopped", "stop_reason": "person"}, "stopped"),
        ({"verdict": "done", "stop_reason": "goal_met"}, "done"),
    ],
)
def test_the_verdict_and_its_stop_reason_give_the_status(
    scan: Path, helper: types.ModuleType, fields: dict[str, str], status: str
) -> None:
    helper.emit("scan", "round_finished", {"round": 2, **fields}, scan)

    state = state_of(scan, NOW + timedelta(days=3650))

    assert state.status == status and state.rounds[-1].stop_reason == fields["stop_reason"]


def test_a_closed_finding_keeps_how_it_was_settled(scan: Path, helper: types.ModuleType) -> None:
    helper.emit(
        "scan", "finding_closed", {"round": 1, "step": "facts", "id": 1, "resolution": "false_positive"}, scan
    )

    facts = state_of(scan).rounds[0].runs_of("facts")[0]

    assert [(finding.id, finding.resolution) for finding in facts.findings] == [
        ("1", "false_positive"),
        ("2", None),
    ]
    with pytest.raises(ValidationError, match="resolution"):
        store.parse_event(
            {
                "ts": "2026-11-14T21:00:00Z",
                "event": "finding_closed",
                "round": 1,
                "step": "facts",
                "id": 1,
                "resolution": "magic",
            }
        )


# ---- links that lead out of a repository ----


def test_a_log_that_is_a_link_is_refused_not_followed(scan: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere.jsonl"
    events = scan / ".loops" / "scan" / "events.jsonl"
    elsewhere.write_text(events.read_text())
    events.unlink()
    events.symlink_to(elsewhere)

    with pytest.raises(store.StoreError, match="not a regular file"):
        store.read_events(scan, "scan")


def test_a_loops_folder_that_is_a_link_holds_no_loop(scan: Path, tmp_path: Path) -> None:
    moved = tmp_path / "moved-loops"
    (scan / ".loops").rename(moved)
    (scan / ".loops").symlink_to(moved)

    assert store.loop_ids(scan) == []


def test_the_manifest_is_not_written_through_a_link_out_of_the_repository(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / ".loops").symlink_to(outside)

    with pytest.raises(store.StoreError, match="leads out of"):
        store.write_manifest(repo, Manifest(id="scan", title="Scan"))

    assert list(outside.iterdir()) == []


# ---- what validate catches beyond the shape of a line ----


def write_events(repo: Path, *lines: dict[str, object]) -> None:
    path = repo / ".loops" / "scan" / "events.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))


def test_validate_catches_a_missing_artifact_time_going_back_and_two_verdicts(
    repo: Path, helper: types.ModuleType
) -> None:
    helper.register("scan", {"title": "Scan"}, repo)
    write_events(
        repo,
        {"ts": "2026-11-14T10:00:00Z", "event": "round_started", "round": 1},
        {
            "ts": "2026-11-14T10:05:00Z",
            "event": "step_finished",
            "round": 1,
            "step": "a",
            "artifact": "gone.md",
        },
        {"ts": "2026-11-14T09:00:00Z", "event": "round_finished", "round": 1, "verdict": "continue"},
        {"ts": "2026-11-14T10:10:00Z", "event": "round_finished", "round": 1, "verdict": "stopped"},
    )

    problems = validate_repo(repo)

    assert any("gone.md does not exist" in line for line in problems)
    assert any("earlier than the one before it" in line for line in problems)
    assert any("finished twice, as continue and as stopped" in line for line in problems)


def test_validate_warns_of_a_back_produced_round_and_an_unread_inbox(
    repo: Path, helper: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    helper.register("scan", {"title": "Scan"}, repo)
    same = "2026-11-14T10:00:00Z"
    write_events(
        repo,
        {"ts": same, "event": "round_started", "round": 1},
        {"ts": same, "event": "step_finished", "round": 1, "step": "a"},
        {"ts": same, "event": "step_finished", "round": 1, "step": "b"},
        {"ts": same, "event": "round_finished", "round": 1, "verdict": "continue"},
    )

    sent = {"id": "s1", "ts": "2026-11-14T10:30:00Z", "kind": "stop"}
    store.append_line(repo / ".loops" / "scan" / "inbox.jsonl", json.dumps(sent))
    later = {"ts": "2026-11-14T11:00:00Z", "event": "round_started", "round": 2}
    store.append_line(repo / ".loops" / "scan" / "events.jsonl", json.dumps(later))

    assert main(["validate", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "warning: scan/events.jsonl: round 1: all 2 steps share one time" in out
    assert "1 entry sent before a round began and never taken" in out and "ok, 2 warning(s)" in out
    assert main(["validate", "--strict", str(repo)]) == 1


def test_the_command_line_says_its_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])

    assert capsys.readouterr().out.startswith("loopcaptain 0.")


def test_emit_command_takes_a_value_of_digits_as_text_where_the_field_is_text(
    scan: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    codes = [
        main(["emit", "scan", "question", "text=true", "round=2", "blocks=true", "--repo", str(scan)]),
        main(["emit", "scan", "heartbeat", "text=42", "--repo", str(scan)]),
        main(
            [
                "emit",
                "scan",
                "round_finished",
                "round=2",
                "verdict=done",
                "commit=1234567",
                "--repo",
                str(scan),
            ]
        ),
        main(["emit", "scan", "round_finished", "round=two", "verdict=done", "--repo", str(scan)]),
        main(["emit", "scan", "check", "item=7", "kind=null", "result=1", "--repo", str(scan)]),
    ]

    question, heartbeat, finished = store.read_events(scan, "scan")[0][-3:]
    assert codes == [0, 0, 0, 1, 1]
    assert isinstance(question, Question) and (question.text, question.round, question.blocks) == (
        "true",
        2,
        True,
    )
    assert getattr(heartbeat, "text", None) == "42" and getattr(finished, "commit", None) == "1234567"
    errors = capsys.readouterr().err
    assert "round_finished.round" in errors and "check.result: Input should be 'pass'" in errors


def test_emit_command_refuses_an_event_that_would_stay_a_problem(
    scan: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = len(store.read_events(scan, "scan")[0])

    code = main(["emit", "scan", "step_finished", "round=9", "step=plan", "--repo", str(scan)])

    assert code == 1 and len(store.read_events(scan, "scan")[0]) == before
    assert "not recorded: round 9 has not started" in capsys.readouterr().err


def test_emit_command_says_how_values_are_read(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["emit", "--help"])

    assert "a value is read as JSON where it parses" in " ".join(capsys.readouterr().out.split())
