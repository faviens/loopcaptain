"""A released package points its prompts at its own tag, a checkout at the branch."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path

import pytest

from loopcaptain import prompts

ROOT = Path(__file__).resolve().parents[1]


def test_only_a_released_version_has_a_tag() -> None:
    assert prompts.release_tag("0.3.1") == "v0.3.1"
    assert prompts.release_tag("0.0.0") == ""
    assert prompts.release_tag("0.4.0.dev1") == ""


def test_a_checkout_shows_the_prompts_as_the_repository_holds_them() -> None:
    for name in prompts.NAMES:
        assert prompts.prompt_text(name) == (ROOT / "standard" / "prompts" / f"{name}.md").read_text()


def test_a_released_package_names_the_runbooks_of_its_own_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metadata, "version", lambda name: "1.2.3")

    shown = prompts.prompts()

    assert "/blob/v1.2.3/AGENTS.md" in shown["watch-my-loops"]
    assert "/blob/v1.2.3/standard/AGENTS.md" in shown["build-a-loop"]
    assert not [name for name, text in shown.items() if prompts.BRANCH in text]


def test_every_prompt_names_a_runbook_the_pin_can_move() -> None:
    for name in prompts.NAMES:
        assert prompts.BRANCH in prompts.prompt_source(name), name


def test_a_package_that_is_not_installed_has_no_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", missing)

    assert prompts.installed_tag() == ""
    with pytest.raises(ValueError, match="no prompt"):
        prompts.prompt_text("other")
