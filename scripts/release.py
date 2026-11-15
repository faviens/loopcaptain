"""Prepare a release: `make release VERSION=x.y.z`. Bumps the version, dates the changelog, commits.

It tags nothing and pushes nothing: the person pushes the tag `vX.Y.Z`, and the release workflow
builds and publishes from that tag.
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
UNRELEASED = "## Unreleased\n"


def date_changelog(text: str, version: str, day: date) -> str:
    """Move the Unreleased section under the version and date, and open an empty Unreleased above."""
    if UNRELEASED not in text:
        raise SystemExit("release: CHANGELOG.md has no '## Unreleased' section")
    head, rest = text.split(UNRELEASED, 1)
    if not rest.strip() or rest.lstrip().startswith("## "):
        raise SystemExit("release: nothing under '## Unreleased' to release")
    return f"{head}{UNRELEASED}\n## {version} - {day.isoformat()}\n{rest}"


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not VERSION.match(argv[0]):
        raise SystemExit("usage: make release VERSION=x.y.z")
    version = argv[0]
    if subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout:
        raise SystemExit("release: the working tree is not clean")
    changelog = ROOT / "CHANGELOG.md"
    changelog.write_text(date_changelog(changelog.read_text(encoding="utf-8"), version, date.today()))
    subprocess.run(["uv", "version", version], cwd=ROOT, check=True)
    subprocess.run(["git", "add", "CHANGELOG.md", "pyproject.toml", "uv.lock"], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-m", f"chore(release): {version}"], cwd=ROOT, check=True)
    sys.stdout.write(
        f"committed {version}; to release it: git tag v{version} && git push origin v{version}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
