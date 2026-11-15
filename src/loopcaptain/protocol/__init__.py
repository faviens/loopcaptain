"""The Loops protocol: the interface between a loop and the board. Start with LOOPS.md."""

from importlib import resources
from pathlib import Path

SPEC_NAME = "LOOPS.md"
#: In a checkout the spec lives in standard/, the folder people and agents are pointed at; a built
#: package carries a copy beside this file (pyproject.toml, force-include).
CHECKOUT_SPEC = Path(__file__).resolve().parents[3] / "standard" / SPEC_NAME


def spec_text() -> str:
    """LOOPS.md, the protocol as loop authors read it."""
    packaged = resources.files(__name__).joinpath(SPEC_NAME)
    if packaged.is_file():
        return packaged.read_text(encoding="utf-8")
    return CHECKOUT_SPEC.read_text(encoding="utf-8")
