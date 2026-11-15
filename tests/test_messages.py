"""The commit-msg hooks take a message about the change and refuse one about the conversation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def hook(name: str) -> re.Pattern[str]:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = [hook for repo in config["repos"] for hook in repo["hooks"]]
    entry = next(hook["entry"] for hook in hooks if hook["id"] == name)
    return re.compile(entry, re.IGNORECASE | re.MULTILINE)


@pytest.mark.parametrize(
    "line",
    [
        "- The user wants the mark removed so nobody thinks it is broken.",
        "- Removed as requested.",
        "- Per the review, the heading is shorter.",
        "- We discussed this and agreed on a table.",
        "- The maintainer does not want readers to see it.",
        "- Fixes what you asked for earlier in this session.",
    ],
)
def test_a_line_about_the_conversation_is_refused(line: str) -> None:
    assert hook("no-conversation").search(f"docs(agents): drop a mark\n\n{line}\n")


@pytest.mark.parametrize(
    "line",
    [
        "- The heading read as a fault although the command works.",
        "- A loop that asks shows its question; the person answers with a button.",
        "- The board shows what the person sent and whether the loop took it.",
        "- Reviews are fresh each round, so a finding is requested again.",
    ],
)
def test_a_line_about_the_change_passes(line: str) -> None:
    assert not hook("no-conversation").search(f"docs(agents): drop a mark\n\n{line}\n")


@pytest.mark.parametrize(
    ("subject", "allowed"),
    [
        ("feat(board): draw the rounds", True),
        ("fix(protocol)!: refuse an unsigned stop", True),
        ("Update the board", False),
        ("feature(board): draw the rounds", False),
    ],
)
def test_a_subject_is_a_conventional_commit(subject: str, allowed: bool) -> None:
    assert bool(hook("conventional-commit").search(subject)) is allowed
