"""The README as a package index shows it: every address absolute, at the release's own tag.

The README links its pictures and the repository's files by relative path, which only the code
host can follow. The package's long description is this text with those paths written out in
full and pinned to the tag of the version being built, so a release's page keeps showing that
release. The build backend calls `ReadmeAtTheTag` (pyproject.toml, `[tool.hatch.metadata.hooks.custom]`);
nothing in a workflow has to run it, and the README in the repository stays as it is.

    uv run python scripts/pypi_readme.py 1.2.3     # print what version 1.2.3 would carry
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

try:
    from hatchling.metadata.plugin.interface import MetadataHookInterface
except ImportError:  # the tests and the command line run without the build backend
    MetadataHookInterface = object

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "main"
UNRELEASED = "0.0.0"
#: Not a path inside the repository: another host, a mail address, a place on the same page.
ELSEWHERE = r"(?![a-z][a-z0-9+.-]*:|#|/)"
PICTURE_ATTRIBUTE = re.compile(rf'\b(src|srcset)="{ELSEWHERE}([^"]+)"')
PICTURE_LINK = re.compile(rf"(!\[[^\]]*\])\({ELSEWHERE}([^)\s]+)\)")
LINK = re.compile(rf"\]\({ELSEWHERE}([^)\s]+)\)")


def ref_of(version: str) -> str:
    """The tag a released version was built from; the branch for a checkout."""
    return BRANCH if version == UNRELEASED else f"v{version}"


def raw_base(repository: str, ref: str) -> str:
    """Where the code host serves a file's bytes, which a picture needs."""
    owner_and_name = repository.rstrip("/").split("://")[-1].split("/", 1)[1]
    return f"https://raw.githubusercontent.com/{owner_and_name}/{ref}"


def absolute(text: str, repository: str, ref: str) -> str:
    """The text with relative pictures and links written in full, and the branch replaced by `ref`."""
    repository = repository.rstrip("/")
    raw, page = raw_base(repository, ref), f"{repository}/blob/{ref}"
    text = PICTURE_ATTRIBUTE.sub(lambda found: f'{found[1]}="{raw}/{found[2]}"', text)
    text = PICTURE_LINK.sub(lambda found: f"{found[1]}({raw}/{found[2]})", text)
    text = LINK.sub(lambda found: f"]({page}/{found[1]})", text)
    return text.replace(f"{repository}/blob/{BRANCH}/", f"{page}/")


def readme_for(version: str, root: Path = ROOT) -> str:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    readme = (root / "README.md").read_text(encoding="utf-8")
    return absolute(readme, project["urls"]["Repository"], ref_of(version))


class ReadmeAtTheTag(MetadataHookInterface):  # type: ignore[misc]
    """Sets the package's long description while the build backend reads the metadata."""

    def update(self, metadata: dict[str, object]) -> None:
        text = readme_for(str(metadata["version"]), Path(self.root))
        metadata["readme"] = {"content-type": "text/markdown", "text": text}


if __name__ == "__main__":
    sys.stdout.write(readme_for(sys.argv[1] if len(sys.argv) > 1 else UNRELEASED))
