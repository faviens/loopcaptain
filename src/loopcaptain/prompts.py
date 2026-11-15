"""The two prompts a person copies into their coding agent to get started.

Their home is `standard/prompts/`; the README, the docs and the board's pages show them from there,
and a built package carries a copy (pyproject.toml, force-include), like LOOPS.md.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

#: Build a loop from nothing, and watch the loops already on this machine.
NAMES = ("build-a-loop", "watch-my-loops")
CHECKOUT = Path(__file__).resolve().parents[2] / "standard" / "prompts"


def prompt_text(name: str) -> str:
    if name not in NAMES:
        raise ValueError(f"no prompt {name!r}; one of {', '.join(NAMES)}")
    packaged = resources.files(__package__ or "loopcaptain").joinpath("prompt_texts", f"{name}.md")
    if packaged.is_file():
        return packaged.read_text(encoding="utf-8")
    return (CHECKOUT / f"{name}.md").read_text(encoding="utf-8")


def prompts() -> dict[str, str]:
    return {name: prompt_text(name) for name in NAMES}
