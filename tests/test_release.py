"""scripts/release.py: the next tag and its notes from the commits since the last one."""

from __future__ import annotations

import importlib.util
import re
import sys
import tomllib
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def release() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while it is being defined
    spec.loader.exec_module(module)
    return module


def test_the_largest_change_decides_the_step(release: types.ModuleType) -> None:
    commit, bump_of = release.Commit, release.bump_of

    assert bump_of([commit("a", "fix(board): x"), commit("b", "feat(protocol): y")]) == "minor"
    assert bump_of([commit("a", "fix(board): x"), commit("b", "perf: y")]) == "patch"
    assert bump_of([commit("a", "feat(protocol)!: drop a field")]) == "major"
    assert bump_of([commit("a", "fix: x", "BREAKING CHANGE: the inbox key moves")]) == "major"


def test_housekeeping_alone_makes_no_release(release: types.ModuleType) -> None:
    commit = release.Commit
    commits = [
        commit("a", "docs: x"),
        commit("b", "chore(agent): y"),
        commit("c", "ci: z"),
        commit("d", "Merge x"),
    ]

    assert release.bump_of(commits) is None


def test_the_tag_counts_up_from_the_last_one(release: types.ModuleType) -> None:
    next_tag = release.next_tag

    assert next_tag(None, "minor") == "v0.1.0", "the first release"
    assert next_tag("v0.3.2", "patch") == "v0.3.3"
    assert next_tag("v0.3.2", "minor") == "v0.4.0"
    assert next_tag("v0.3.2", "major") == "v0.4.0", "before 1.0 a breaking change is a minor step"
    assert next_tag("v1.3.2", "major") == "v2.0.0"


def test_the_notes_list_what_users_notice_under_headings(release: types.ModuleType) -> None:
    commit = release.Commit

    text = release.notes(
        [
            commit("1234567890", "feat(board): draw each loop's latest rounds"),
            commit("abcdef1234", "fix(protocol): refuse an unsigned stop"),
            commit("ffffffffff", "test(board): keep the table readable"),
        ]
    )

    assert "## New\n\n- **board**: draw each loop's latest rounds (1234567)" in text
    assert "## Fixed\n\n- **protocol**: refuse an unsigned stop (abcdef1)" in text
    assert "keep the table readable" not in text


def test_the_checkout_carries_no_version_of_its_own() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["version"] == "0.0.0", "a release stamps its tag into the wheel; nothing is committed back"


def test_a_release_is_built_by_one_named_version_of_the_build_backend() -> None:
    """The build backend is not in the lock file: unpinned, a release builds with whatever is newest."""
    build = tomllib.loads((ROOT / "pyproject.toml").read_text())["build-system"]

    assert [re.fullmatch(r"hatchling==\d+\.\d+\.\d+", item) is not None for item in build["requires"]] == [
        True
    ]


def test_the_source_archive_leaves_out_what_only_the_repository_needs() -> None:
    """Pictures of the documentation, ledgers, CI files and a local cache made the archive four times larger."""
    settings = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    left_out = settings["tool"]["hatch"]["build"]["targets"]["sdist"]["exclude"]

    assert {"/.agent", "/.github", "/.cache", "/docs/assets"} <= set(left_out)
    assert not {"/src", "/standard", "/scripts", "/tests"} & set(left_out)  # what builds and tests it stays


def test_the_package_points_at_the_releases_for_what_changed() -> None:
    """CHANGELOG.md holds the first version only; every later note is on the releases page."""
    urls = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["urls"]

    assert urls["Changelog"].endswith("/releases")
