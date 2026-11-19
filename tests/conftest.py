"""Shared fixtures: a temporary repository and the paste-in helper exactly as the spec prints it."""

from __future__ import annotations

import json
import re
import types
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from loopcaptain.protocol import spec_text

STEPS: list[dict[str, Any]] = [
    {"id": "plan", "kind": "plan"},
    {"id": "research", "kind": "research"},
    {"id": "build", "kind": "build"},
    {"id": "facts", "kind": "review", "after": ["build"]},
    {"id": "reader", "kind": "review", "after": ["build"]},
    {"id": "gate", "kind": "gate", "after": ["facts", "reader"]},
    {"id": "verdict", "kind": "verdict"},
]


def helper_source() -> str:
    """The first Python block of LOOPS.md section 4: the helper a loop author pastes."""
    section = spec_text().split("## 4. The helper to paste", 1)[1]
    found = re.search(r"```python\n(.*?)```", section, re.S)
    if found is None:
        raise AssertionError("LOOPS.md section 4 holds no python block")
    return found.group(1)


@pytest.fixture(autouse=True)
def inbox_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test signs with its own key, never with the one in the user's config folder."""
    path = tmp_path / "inbox.key"
    monkeypatch.setenv("LOOPCAPTAIN_INBOX_KEY", str(path))
    return path


@pytest.fixture
def helper() -> types.ModuleType:
    module = types.ModuleType("pasted_loopcaptain")
    exec(compile(helper_source(), "LOOPS.md", "exec"), module.__dict__)
    return module


def name_files(repo: Path, *paths: str, loop: str = "scan") -> None:
    """Let a loop name files, as a step that made them would: the board opens no other."""
    with (repo / ".loops" / loop / "events.jsonl").open("a", encoding="utf-8") as log:
        for path in paths:
            stamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            line = {"ts": stamp, "event": "step_finished", "round": 2, "step": "plan", "artifact": path}
            log.write(json.dumps(line) + "\n")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "some-repo"
    path.mkdir()
    return path


@pytest.fixture
def scan(repo: Path, helper: types.ModuleType) -> Path:
    """A repository with one loop, `scan`: round 1 finished with a finding, round 2 under way."""
    helper.register("scan", {"title": "Market scan", "steps": STEPS, "round_cap": 5}, repo)
    emit = helper.emit
    emit("scan", "round_started", {"round": 1, "plan": "First pass."}, repo)
    emit(
        "scan",
        "step_finished",
        {"round": 1, "step": "plan", "cost": {"usd": 0.5, "tokens_in": 100, "tokens_out": 10}},
        repo,
    )
    emit(
        "scan",
        "step_finished",
        {"round": 1, "step": "research", "label": "pricing", "summary": "Five prices."},
        repo,
    )
    emit(
        "scan",
        "step_finished",
        {"round": 1, "step": "research", "label": "vendors", "status": "failed"},
        repo,
    )
    emit(
        "scan",
        "step_finished",
        {
            "round": 1,
            "step": "facts",
            "findings": [
                {"id": 1, "text": "No source for 40 percent."},
                {"id": 2, "text": "Typo.", "severity": "minor"},
            ],
            "cost": {"usd": 0.25},
        },
        repo,
    )
    emit("scan", "finding_closed", {"round": 1, "step": "facts", "id": 2, "reason": "Fixed."}, repo)
    emit(
        "scan",
        "round_finished",
        {"round": 1, "verdict": "continue", "summary": "One fact open.", "commit": "abc1234"},
        repo,
    )
    emit("scan", "round_started", {"round": 2, "plan": "Close the fact."}, repo)
    emit("scan", "step_started", {"round": 2, "step": "plan"}, repo)
    return repo
