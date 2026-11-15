"""The project is neutral: no company or client name in anything that is committed.

The refused names live in `.forbidden-words.local`, one per line, never committed: the same list the
pre-commit hook `scripts/forbidden_words.sh` reads. Without that file the check is skipped, because a
list written into this file would itself name what it refuses.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORD_LIST = ROOT / ".forbidden-words.local"
SKIPPED_SUFFIXES = {".woff2", ".webp", ".png", ".lock"}


def refused_words(path: Path) -> list[str]:
    """The words of a list file: one per line, `#` starts a comment line, blank lines ignored."""
    if not path.is_file():
        return []
    lines = (line.strip().lower() for line in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def addresses_of(repository: str) -> list[str]:
    """Where the repository lives: its path as badges name it, and its documentation site.

    An address, not a name the project gives out. `https://github.com/owner/repo` gives
    `owner.github.io/repo` and `owner/repo`, which also covers the address itself.
    """
    parts = repository.split("://")[-1].strip("/").lower().split("/")
    if len(parts) < 3:
        return []
    owner, repo = parts[1], parts[2]
    return [f"{owner}.github.io/{repo}", f"{owner}/{repo}"]


def own_addresses() -> list[str]:
    urls = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"].get("urls", {})
    return addresses_of(str(urls.get("Repository", "")))


def committed_or_new_files() -> list[Path]:
    """Every file git would track: committed, staged or untracked and not ignored."""
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    paths = [ROOT / line for line in listed.stdout.splitlines() if line]
    return [path for path in paths if path.is_file() and path.suffix not in SKIPPED_SUFFIXES]


def test_the_list_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    listed = tmp_path / "words"
    listed.write_text("# a comment\n\nAlpha\n  beta  \n", encoding="utf-8")

    assert refused_words(listed) == ["alpha", "beta"]
    assert refused_words(tmp_path / "missing") == []


def test_own_addresses_are_the_path_and_the_site() -> None:
    assert addresses_of("https://github.com/Owner/repo/") == ["owner.github.io/repo", "owner/repo"]
    assert addresses_of("") == []


def test_the_hook_lets_the_own_addresses_pass_and_refuses_the_name(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('Repository = "https://github.com/acme/thing"\n')
    (tmp_path / ".forbidden-words.local").write_text("acme\n")
    (tmp_path / "badges.md").write_text(
        "shields.io/x/acme/thing acme.github.io/thing/ github.com/acme/thing\n"
    )
    (tmp_path / "named.md").write_text("Made by Acme.\n")

    def hook(name: str) -> int:
        script = ROOT / "scripts" / "forbidden_words.sh"
        return subprocess.run(["sh", str(script), name], cwd=tmp_path, capture_output=True).returncode

    assert (hook("badges.md"), hook("named.md")) == (0, 1)


def test_no_refused_name_is_in_the_repository() -> None:
    refused = refused_words(WORD_LIST)
    if not refused:
        pytest.skip(f"{WORD_LIST.name} is missing or empty: the names to refuse are kept only on a laptop")
    found = []
    addresses = own_addresses()
    for path in committed_or_new_files():
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for address in addresses:
            text = text.replace(address, "")
        found += [
            f"{path.relative_to(ROOT)}: word {refused.index(word) + 1}" for word in refused if word in text
        ]

    assert found == []


def test_no_study_of_other_products_is_committed() -> None:
    """A standard carries no comparison of named products: the study lives outside the repository."""
    files = committed_or_new_files()

    assert not [path for path in files if "research" in path.relative_to(ROOT).parts]
    mentions = [
        path.relative_to(ROOT).as_posix()
        for path in files
        if path.name != "test_neutral.py"
        and "docs/research" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not mentions, mentions


def test_the_repository_names_its_own_address_and_nothing_else_needs_a_placeholder() -> None:
    site, path = own_addresses()

    assert site.endswith(".github.io/loopcaptain") and path.endswith("/loopcaptain")
    left = [
        path.relative_to(ROOT).as_posix()
        for path in committed_or_new_files()
        if path.name != "test_neutral.py"
        and "REPOSITORY_URL" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not left, left
