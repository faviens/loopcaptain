"""The MCP tools write the same files the pasted helper writes."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, get_args

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from loopcaptain.mcp_server import server as mcp
from loopcaptain.protocol import signing, store
from loopcaptain.protocol.models import AnyEvent
from loopcaptain.protocol.validate import validate_repo
from tests.conftest import STEPS

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
        (lambda repo: mcp.emit("plan-loop", "inbox_read", {"ids": []}, repo=repo), "not an event to emit"),
        (lambda repo: mcp.emit("plan-loop", "made_up", {}, repo=repo), "One of: round_started"),
    ],
)
def test_a_bad_call_is_refused_in_one_line(repo: Path, call: Any, message: str) -> None:
    register(repo)

    with pytest.raises(ToolError, match=message):
        call(str(repo))


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
    signing.board_key()
    store.append_inbox(repo, "plan-loop", "stop", key=signing.board_key())
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
