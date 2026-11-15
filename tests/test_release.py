"""The release settings agree with the package: the version, the name, the changelog's form."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_last_released_version_is_the_package_version() -> None:
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text(encoding="utf-8"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert manifest == {".": project["version"]}


def test_the_release_names_the_package_and_keeps_the_lock_in_step() -> None:
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    package = config["packages"]["."]

    assert config["release-type"] == "python" and package["package-name"] == "loopcaptain"
    assert [extra["path"] for extra in package["extra-files"]] == ["uv.lock"]


def test_the_changelog_starts_with_a_version_the_release_can_write_above() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^## (.+)$", changelog, flags=re.MULTILINE)

    assert first is not None and re.match(r"\[?\d+\.\d+\.\d+", first.group(1)), (
        "no hand-kept Unreleased section"
    )
