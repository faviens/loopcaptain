"""The MCP tools write the same files the pasted helper writes."""

from __future__ import annotations

import asyncio
import re
import sys
import time
import tomllib
from pathlib import Path
from typing import Any, get_args

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from loopcaptain.cli import main
from loopcaptain.mcp_server import server as mcp
from loopcaptain.protocol import signing, store
from loopcaptain.protocol.models import AnyEvent
from loopcaptain.protocol.validate import validate_repo
from tests.conftest import STEPS

ROOT = Path(__file__).resolve().parents[1]

MANIFEST: dict[str, Any] = {
    "title": "Planning rounds",
    "brief": {"goal": "Decide the design."},
    "steps": STEPS,
    "round_cap": 4,
    "outputs": [{"name": "memo", "path": "out/memo.md"}],
}


@pytest.fixture(autouse=True)
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The tests' repositories sit in a temporary folder, outside the folder the tests run in."""
    monkeypatch.setenv("LOOPCAPTAIN_MCP_ROOTS", str(tmp_path))


def test_a_repo_outside_the_working_folder_and_the_roots_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inner, outer = tmp_path / "work", tmp_path / "other"
    (inner / "sub").mkdir(parents=True)
    outer.mkdir()
    monkeypatch.delenv("LOOPCAPTAIN_MCP_ROOTS")
    monkeypatch.chdir(inner)

    assert mcp.loop_status(repo="sub") == {"loops": []}
    assert mcp.loop_status() == {"loops": []}
    with pytest.raises(ToolError, match="outside"):
        mcp.loop_status(repo=str(outer))
    with pytest.raises(ToolError, match="outside"):
        mcp.loop_status(repo="..")

    monkeypatch.setenv("LOOPCAPTAIN_MCP_ROOTS", str(outer))
    assert mcp.loop_status(repo=str(outer)) == {"loops": []}


def register(repo: Path) -> None:
    mcp.loop_register("plan-loop", MANIFEST, repo=str(repo))


def emit(repo: Path, event: str, fields: dict[str, Any]) -> None:
    mcp.emit("plan-loop", event, fields, repo=str(repo))


def test_a_round_reported_through_the_tools_validates_and_folds(repo: Path) -> None:
    register(repo)
    emit(repo, "round_started", {"round": 1, "plan": "First pass."})
    emit(
        repo,
        "step_finished",
        {"round": 1, "step": "facts", "findings": [{"id": 1, "text": "No source."}], "cost": {"usd": 0.4}},
    )
    emit(repo, "finding_closed", {"round": 1, "step": "facts", "id": 1, "resolution": "fixed"})
    emit(repo, "check", {"item": "Tool A", "kind": "own trial", "result": "pass"})
    emit(repo, "question", {"text": "Which of the two?", "round": 1})
    emit(
        repo,
        "round_finished",
        {"round": 1, "verdict": "wait", "reason": "person", "summary": "One question."},
    )

    status = mcp.loop_status("plan-loop", repo=str(repo))

    assert validate_repo(repo) == []
    assert status["status"] == "waiting" and status["open_question"] == "Which of the two?"
    assert (status["rounds"], status["open_findings"], status["cost_usd"]) == (1, [], 0.4)
    assert mcp.loop_status(repo=str(repo)) == {"loops": ["plan-loop"]}
    assert [output.path for output in store.read_manifest(repo, "plan-loop").outputs] == ["out/memo.md"]


def test_inbox_read_returns_each_entry_once(repo: Path) -> None:
    register(repo)
    store.append_inbox(repo, "plan-loop", "reply", "The second.")
    store.append_inbox(repo, "plan-loop", "stop")

    first = mcp.inbox_read("plan-loop", repo=str(repo))
    second = mcp.inbox_read("plan-loop", repo=str(repo))

    assert [(entry["kind"], entry.get("text", "")) for entry in first] == [
        ("reply", "The second."),
        ("stop", ""),
    ]
    assert second == []


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (
            lambda repo: mcp.emit("ghost", "round_started", {"round": 1}, repo=repo),
            "Call loop_register first",
        ),
        (
            lambda repo: mcp.loop_register("x", {"steps": [{"id": "a", "after": ["nope"]}]}, repo=repo),
            "unknown step",
        ),
        (
            lambda repo: mcp.emit(
                "plan-loop",
                "step_finished",
                {"round": 1, "step": "facts", "artifact": "/etc/passwd"},
                repo=repo,
            ),
            "inside the repository",
        ),
        (
            lambda repo: mcp.emit("plan-loop", "round_started", {"round": 0}, repo=repo),
            "greater than or equal to 1",
        ),
        (
            lambda repo: mcp.emit(
                "plan-loop", "round_finished", {"round": 1, "verdict": "perhaps"}, repo=repo
            ),
            "verdict",
        ),
        (
            lambda repo: mcp.emit("plan-loop", "step_finished", {"round": 5, "step": "facts"}, repo=repo),
            "not recorded: round 5 has not started: emit round_started for it first",
        ),
        (
            lambda repo: mcp.emit("plan-loop", "round_finished", {"round": 5, "verdict": "done"}, repo=repo),
            "round 5 has not started",
        ),
        (lambda repo: mcp.emit("plan-loop", "made_up", {}, repo=repo), "One of: round_started"),
    ],
)
def test_a_bad_call_is_refused_in_one_line(repo: Path, call: Any, message: str) -> None:
    register(repo)

    with pytest.raises(ToolError, match=message):
        call(str(repo))


def test_an_inbox_line_this_version_cannot_read_can_still_be_marked_read(repo: Path) -> None:
    register(repo)
    with (repo / ".loops" / "plan-loop" / "inbox.jsonl").open("a") as inbox:
        inbox.write('{"id": "later-1", "ts": "2026-11-15T08:00:00Z", "kind": "pause"}\n')

    said = mcp.emit("plan-loop", "inbox_read", {"ids": ["later-1"]}, repo=str(repo))

    assert said.startswith("inbox_read recorded; warning: ids: 'later-1' is not an entry")
    assert store.read_events(repo, "plan-loop")[0][-1].event == "inbox_read"


def test_a_log_too_large_to_check_still_takes_the_event_and_says_so(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    register(repo)
    emit(repo, "round_started", {"round": 1})
    monkeypatch.setattr(store, "MAX_LOG_BYTES", 10)

    said = mcp.emit("plan-loop", "round_finished", {"round": 1, "verdict": "done"}, repo=str(repo))
    code = main(["emit", "plan-loop", "heartbeat", "--repo", str(repo)])

    assert said.startswith("round_finished recorded; warning: events.jsonl:") and "without checking" in said
    assert code == 0 and "without checking it against the log" in capsys.readouterr().err
    lines = (repo / ".loops" / "plan-loop" / "events.jsonl").read_text().splitlines()
    assert [line.split('"event":"')[1].split('"')[0] for line in lines[-2:]] == [
        "round_finished",
        "heartbeat",
    ]


def test_a_refusal_reaches_the_agent_with_its_reason(repo: Path) -> None:
    call = mcp.server.call_tool("emit", {"loop_id": "ghost", "event": "round_started", "repo": str(repo)})

    with pytest.raises(ToolError, match=r"no loop 'ghost' here\. Call loop_register first"):
        asyncio.run(call)


def test_the_server_offers_exactly_the_tools_the_spec_names(repo: Path) -> None:
    listed = {tool.name for tool in asyncio.run(mcp.server.list_tools())}
    spec = mcp.protocol()

    assert listed == {"protocol", "loop_register", "emit", "inbox_read", "loop_status"}
    assert all(f"`{name}`" in spec.split("## 5.")[1] for name in listed)


def test_inbox_read_says_whether_the_board_signed_each_entry(repo: Path) -> None:
    register(repo)
    signing.board_keys()
    store.append_inbox(repo, "plan-loop", "stop", keys=signing.board_keys())
    store.append_inbox(repo, "plan-loop", "reply", "forged")

    taken = mcp.inbox_read("plan-loop", repo=str(repo))

    assert [(entry["kind"], entry["signed"]) for entry in taken] == [("stop", True), ("reply", False)]


EVENT_MODELS = get_args(get_args(AnyEvent)[0])


def test_every_field_the_emit_tool_names_exists_on_its_event() -> None:
    doc = mcp.emit.__doc__ or ""
    adapter_models = {model.model_fields["event"].default: model for model in EVENT_MODELS}

    entries = re.sub(r"\n\s{6,}", " ", doc).splitlines()  # a wrapped entry is one line
    assert sum(1 for line in entries if re.match(r"\s*- \w+:", line)) >= 10
    for line in entries:
        found = re.match(r"\s*- (\w+): (.*)", line)
        if not found or found.group(1) not in adapter_models:
            continue
        model = adapter_models[found.group(1)]
        named = re.findall(r"(?:^|, )([a-z_]+)", re.sub(r"[\[{(].*?[\]})]", "", found.group(2)))
        missing = [name for name in named if name not in model.model_fields]
        assert missing == [], f"{found.group(1)} names {missing}"


def test_loop_status_reads_a_far_year_and_an_infinite_cost_without_failing(repo: Path) -> None:
    register(repo)
    emit(repo, "round_started", {"round": 1})
    with (repo / ".loops" / "plan-loop" / "events.jsonl").open("a") as log:
        log.write('{"ts": "9999-12-31T23:00:00Z", "event": "heartbeat", "next_at": "9999-12-31T23:00:00Z"}\n')
        log.write('{"ts": "2026-11-15T08:00:00Z", "event": "step_finished", "round": 1, "step": "facts",')
        log.write(' "cost": {"usd": 1e309}}\n')
        log.write('{"ts": "2026-11-15T08:00:00Z", "event": "heartbeat", "next_at": ')
        log.write("[" * 100_000 + "]" * 100_000 + "}\n")

    status = mcp.loop_status("plan-loop", repo=str(repo))

    assert status["status"] in ("running", "stalled") and status["cost_usd"] == 0
    assert [line.split(":")[1] for line in status["unreadable_lines"]] == ["4"]


def test_a_tool_says_how_to_repair_a_loop_json_it_cannot_read(repo: Path) -> None:
    register(repo)
    (repo / ".loops" / "plan-loop" / "loop.json").write_text('{"protocol": 1,', encoding="utf-8")

    with pytest.raises(ToolError, match=r"Invalid JSON.*Call loop_register again"):
        mcp.loop_status("plan-loop", repo=str(repo))


def test_emit_refuses_what_validate_would_call_a_problem_and_writes_nothing(repo: Path) -> None:
    register(repo)
    emit(repo, "round_started", {"round": 1})
    emit(repo, "round_finished", {"round": 1, "verdict": "continue"})
    before = len(store.read_events(repo, "plan-loop")[0])
    refused = [
        (
            "step_finished",
            {"round": 1, "step": "mystery"},
            "step 'mystery' is not in loop.json, which has plan",
        ),
        ("step_started", {"round": 2, "step": "plan"}, "round 2 has not started"),
        (
            "step_finished",
            {"round": 1, "step": "plan", "artifact": "work/plan.md"},
            "work/plan.md does not exist",
        ),
        ("round_finished", {"round": 1, "verdict": "failed"}, "finished twice, as continue and as failed"),
    ]

    for event, fields, message in refused:
        with pytest.raises(ToolError, match=message):
            emit(repo, event, fields)
    unchanged = len(store.read_events(repo, "plan-loop")[0])
    (repo / "work").mkdir()
    (repo / "work" / "plan.md").write_text("The plan.\n")
    emit(repo, "step_finished", {"round": 1, "step": "plan", "artifact": "work/plan.md"})
    emit(repo, "round_finished", {"round": 1, "verdict": "continue"})

    assert unchanged == before and validate_repo(repo) == []


def test_a_loop_that_reads_the_inbox_file_itself_marks_its_entries_read_through_emit(repo: Path) -> None:
    register(repo)
    sent = store.append_inbox(repo, "plan-loop", "reply", "The second.")

    emit(repo, "inbox_read", {"ids": [sent.id]})

    assert mcp.inbox_read("plan-loop", repo=str(repo)) == []


def test_inbox_read_marks_a_reply_to_an_earlier_asking_as_stale(repo: Path) -> None:
    register(repo)
    emit(repo, "question", {"id": "design", "text": "Which of the two?"})
    time.sleep(0.002)
    store.append_inbox(repo, "plan-loop", "reply", "The first.", question="design")
    time.sleep(0.002)
    emit(repo, "question", {"id": "design", "text": "Which of the two, now?"})
    time.sleep(0.002)
    store.append_inbox(repo, "plan-loop", "reply", "The second.", question="design")

    taken = mcp.inbox_read("plan-loop", repo=str(repo))

    assert [(entry["text"], entry["stale"]) for entry in taken] == [
        ("The first.", True),
        ("The second.", False),
    ]


def test_finding_closed_before_its_round_is_written_as_validate_allows(tmp_path: Path) -> None:
    from loopcaptain.protocol.models import EVENT, Manifest
    from loopcaptain.protocol.validate import refusals

    manifest = Manifest.model_validate({"protocol": 1, "id": "x", "name": "x"})
    event = EVENT.validate_python(
        {"ts": "2026-11-16T08:00:00Z", "event": "finding_closed", "round": 3, "step": "a", "id": "f1"}
    )
    assert refusals(tmp_path, manifest, [], event) == []


def test_the_mcp_server_is_an_extra_and_says_so_where_it_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The SDK was about half of a plain install, and the board and the helper never load it."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert not [name for name in project["dependencies"] if name.startswith("mcp")]
    assert project["optional-dependencies"]["mcp"] == ["mcp>=2.0"]
    monkeypatch.delitem(sys.modules, "loopcaptain.mcp_server.server", raising=False)
    for name in ("mcp", "mcp.server", "mcp.server.mcpserver"):  # as on a machine without the extra
        monkeypatch.setitem(sys.modules, name, None)

    assert main(["mcp"]) == 1
    assert "uv tool install 'loopcaptain[mcp]'" in capsys.readouterr().err
    assert main(["mcp-config", "claude-code", "--checkout", ""]) == 0
    assert "the server needs the MCP extra" in capsys.readouterr().out
