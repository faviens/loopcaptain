"""The next release from the commits since the last tag (docs/ARCHITECTURE.md, section 19).

CI runs it on every push to main: a `feat` since the last tag raises the minor version, a `fix` or
`perf` the patch, a breaking change the major (the minor while the major is 0); `docs`, `test`,
`chore`, `ci` and `refactor` make no release. It prints the new tag and writes the release notes,
so nobody bumps a version or opens a pull request for one.

    uv run --no-project python scripts/release.py --notes dist/release-notes.md
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
SUBJECT = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?: (?P<text>.+)$")
FIELD, RECORD = "\x1f", "\x1e"
HEADINGS = {"feat": "New", "fix": "Fixed", "perf": "Faster"}


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str
    body: str = ""


def bump_of(commits: list[Commit]) -> str | None:
    """The largest change among the commits: major, minor, patch, or None for no release."""
    found: set[str] = set()
    for commit in commits:
        match = SUBJECT.match(commit.subject)
        if not match:
            continue
        if match["bang"] or "BREAKING CHANGE" in commit.body:
            found.add("major")
        elif match["type"] == "feat":
            found.add("minor")
        elif match["type"] in ("fix", "perf"):
            found.add("patch")
    return next((bump for bump in ("major", "minor", "patch") if bump in found), None)


def version_of(tag: str | None) -> tuple[int, int, int]:
    match = TAG.match(tag or "")
    return (int(match[1]), int(match[2]), int(match[3])) if match else (0, 0, 0)


def next_tag(last: str | None, bump: str) -> str:
    major, minor, patch = version_of(last)
    if bump == "major" and major == 0:
        bump = "minor"  # before 1.0 a breaking change is a minor step
    if bump == "major":
        return f"v{major + 1}.0.0"
    if bump == "minor":
        return f"v{major}.{minor + 1}.0"
    return f"v{major}.{minor}.{patch + 1}"


def notes(commits: list[Commit]) -> str:
    """The release notes: each feat, fix and perf subject under its heading, newest first."""
    sections: dict[str, list[str]] = {kind: [] for kind in HEADINGS}
    for commit in commits:
        match = SUBJECT.match(commit.subject)
        if match and match["type"] in sections:
            scope = f"**{match['scope']}**: " if match["scope"] else ""
            sections[match["type"]].append(f"- {scope}{match['text']} ({commit.sha[:7]})")
    return "\n\n".join(
        f"## {HEADINGS[kind]}\n\n" + "\n".join(lines) for kind, lines in sections.items() if lines
    )


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def last_tag() -> str | None:
    tags = [t for t in git("tag", "--merged", "HEAD", "--list", "v*").split() if TAG.match(t)]
    return max(tags, key=version_of, default=None)


def commits_since(tag: str | None) -> list[Commit]:
    span = f"{tag}..HEAD" if tag else "HEAD"
    out = git("log", "--no-merges", f"--format=%H{FIELD}%s{FIELD}%b{RECORD}", span)
    return [Commit(*entry.strip("\n").split(FIELD, 2)) for entry in out.split(RECORD) if entry.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notes", type=Path, required=True, help="where to write the release notes")
    args = parser.parse_args()
    tag = last_tag()
    commits = commits_since(tag)
    bump = bump_of(commits)
    if bump is None:
        return  # nothing for users since the last tag: no release, no output
    args.notes.parent.mkdir(parents=True, exist_ok=True)
    # The first tag would list the whole history; git log keeps that.
    args.notes.write_text((notes(commits) if tag else "The first release.") + "\n")
    sys.stdout.write(next_tag(tag, bump) + "\n")


if __name__ == "__main__":
    main()
