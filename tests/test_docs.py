"""The documentation pages written from the code are current, and the site builds."""

from __future__ import annotations

import importlib.util
import tomllib
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def docs_pages() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("docs_pages", ROOT / "scripts" / "docs_pages.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_generated_pages_are_current(docs_pages: types.ModuleType) -> None:
    stale = [
        str(path.relative_to(ROOT)) for path, text in docs_pages.pages().items() if path.read_text() != text
    ]

    assert stale == [], "run make docs-pages"


def test_every_command_has_its_section(docs_pages: types.ModuleType) -> None:
    page = docs_pages.cli_page()

    for command in ("serve", "validate", "doctor", "watch", "demo", "mcp-config", "emit"):
        assert f"## `{command}`" in page


@pytest.fixture(scope="module")
def readme_assets() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("readme_assets", ROOT / "scripts" / "readme_assets.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_architecture_picture_is_current_and_linked(readme_assets: types.ModuleType, theme: str) -> None:
    drawn = ROOT / "docs" / "assets" / f"parts-{theme}.svg"

    assert drawn.read_text(encoding="utf-8") == readme_assets.parts_picture(theme), "run make readme"
    assert f"assets/parts-{theme}.svg" in (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")


def test_the_first_screen_says_what_it_is_in_the_words_people_search() -> None:
    opening = (ROOT / "README.md").read_text(encoding="utf-8").split("## Get started")[0].lower()
    description = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["description"]
    site = tomllib.loads((ROOT / "zensical.toml").read_text())["project"]["site_description"]

    for word in ("open protocol", "agent loop", "dashboard", "monitor", "steer", "human in the loop"):
        assert word in opening, word
    assert description == site and len(description) <= 120
