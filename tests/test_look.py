"""The look: paper, ink and one red, the same on the board and in every drawn picture."""

from __future__ import annotations

import importlib.util
import re
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "src" / "loopcaptain" / "board" / "static" / "style.css"
#: The accent the look replaced, in every spelling it had.
OLD_ACCENT = ("4A3FE0", "A8A1FF", "74 63 224", "168 161 255", "0E0A3A")
ROLES = ("paper", "ink", "grey", "accent")


def pictures() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("readme_assets", ROOT / "scripts" / "readme_assets.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def board_colours() -> dict[str, dict[str, str]]:
    """Each role's colour as hex, light from the first `:root`, dark from the media query's."""
    sheet = STYLE.read_text(encoding="utf-8")
    light, dark = sheet.split("@media (prefers-color-scheme: dark)", 1)
    found: dict[str, dict[str, str]] = {}
    for theme, block in (("light", light), ("dark", dark)):
        found[theme] = {}
        for role in ROLES:
            rgb = re.search(rf"--rgb-{role}: (\d+) (\d+) (\d+);", block)
            assert rgb, f"{theme} {role}"
            found[theme][role] = "#" + "".join(f"{int(part):02X}" for part in rgb.groups())
    return found


def test_the_board_and_the_pictures_share_paper_ink_and_one_red() -> None:
    drawn = pictures().THEMES
    board = board_colours()

    for theme in ("light", "dark"):
        assert {role: drawn[theme][role].upper() for role in ROLES} == board[theme], theme
    assert board["light"]["accent"] == "#D6000B" and board["dark"]["accent"] == "#FF6B73"


def test_no_trace_of_the_old_accent_is_left() -> None:
    places = [STYLE, ROOT / "scripts" / "readme_assets.py", *sorted((ROOT / "docs" / "assets").glob("*.svg"))]
    places += sorted((ROOT / "src" / "loopcaptain" / "board").rglob("*.svg"))

    left = [
        path.name for path in places if any(old in path.read_text(encoding="utf-8") for old in OLD_ACCENT)
    ]

    assert left == []
