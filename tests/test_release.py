"""Preparing a release dates the changelog and refuses what it cannot release."""

from __future__ import annotations

import importlib.util
import types
from datetime import date
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release.py"


@pytest.fixture(scope="module")
def release() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("release", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_unreleased_section_moves_under_the_version_and_date(release: types.ModuleType) -> None:
    text = "# Changelog\n\n## Unreleased\n\n### Added\n\n1. A thing.\n"

    dated = release.date_changelog(text, "0.2.0", date(2026, 11, 15))

    assert dated == "# Changelog\n\n## Unreleased\n\n## 0.2.0 - 2026-11-15\n\n### Added\n\n1. A thing.\n"


def test_an_empty_unreleased_section_is_not_released(release: types.ModuleType) -> None:
    with pytest.raises(SystemExit, match="nothing under"):
        release.date_changelog(
            "# Changelog\n\n## Unreleased\n\n## 0.1.0 - 2026-11-01\n", "0.2.0", date.today()
        )
