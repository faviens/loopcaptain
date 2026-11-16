"""The two prompts a person copies into their coding agent to get started.

Their home is `standard/prompts/`; the README, the docs and the board's pages show them from there,
and a built package carries a copy (pyproject.toml, force-include), like LOOPS.md.

The text in the repository names the runbooks on the `main` branch. A released package shows the
same prompts with the address of its own tag, so the agent reads the runbook of the release the
person installed and not whatever the branch holds that day.
"""

from __future__ import annotations

import re
from importlib import metadata, resources
from pathlib import Path

#: Build a loop from nothing, and watch the loops already on this machine.
NAMES = ("build-a-loop", "watch-my-loops")
CHECKOUT = Path(__file__).resolve().parents[2] / "standard" / "prompts"
#: How an address names a file on the moving branch, and the version nothing released carries.
BRANCH = "/blob/main/"
RELEASED = re.compile(r"^\d+\.\d+\.\d+$")
UNRELEASED = "0.0.0"


def release_tag(version: str) -> str:
    """The tag of a released version; "" for a checkout or an install from the branch."""
    return f"v{version}" if RELEASED.match(version) and version != UNRELEASED else ""


def installed_tag() -> str:
    try:
        return release_tag(metadata.version("loopcaptain"))
    except metadata.PackageNotFoundError:
        return ""


def pinned(text: str, tag: str) -> str:
    """The text with every address on the branch moved to the tag; unchanged without a tag."""
    return text.replace(BRANCH, f"/blob/{tag}/") if tag else text


def prompt_source(name: str) -> str:
    if name not in NAMES:
        raise ValueError(f"no prompt {name!r}; one of {', '.join(NAMES)}")
    packaged = resources.files(__package__ or "loopcaptain").joinpath("prompt_texts", f"{name}.md")
    if packaged.is_file():
        return packaged.read_text(encoding="utf-8")
    return (CHECKOUT / f"{name}.md").read_text(encoding="utf-8")


def prompt_text(name: str) -> str:
    return pinned(prompt_source(name), installed_tag())


def prompts() -> dict[str, str]:
    return {name: prompt_text(name) for name in NAMES}
