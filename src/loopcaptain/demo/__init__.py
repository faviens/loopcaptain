"""`loopcaptain demo`: the example loop, written into a folder of its own with its first rounds.

The folder gets `loop.py`, the example loop, and `loops.py`, the helper as LOOPS.md prints it: the
same two files any loop needs. Its history is made by running the loop itself with past times.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKOUT_HELPER = HERE.parents[2] / "standard" / "loops.py"
SEEDED_ROUNDS = 2
SEED_TIMEOUT_S = 60
#: What the demo writes into its folder; only these are replaced on a second run.
WRITTEN = (".loops", "work", "out")
#: The file that marks a folder as the demo's own: only such a folder is ever cleared.
MARKER = ".loopcaptain-demo"


class DemoError(Exception):
    """The target is not a folder the demo may write into."""


def helper_source() -> str:
    """The helper: packaged beside this file in a build (force-include), in standard/ in a checkout."""
    packaged = resources.files(__name__).joinpath("loops.py")
    if packaged.is_file():
        return packaged.read_text(encoding="utf-8")
    return CHECKOUT_HELPER.read_text(encoding="utf-8")


def write_demo(target: Path) -> Path:
    """Write the example loop into `target`, replacing what an earlier demo wrote there, and seed it.

    A folder that holds anything and was not made by the demo is refused: it may be a real repository.
    """
    ours = (target / MARKER).is_file()
    if target.exists() and any(target.iterdir()) and not ours:
        raise DemoError(f"{target} is not empty and was not made by the demo; pick a new folder")
    if ours:
        for name in WRITTEN:
            if (target / name).is_dir() and not (target / name).is_symlink():
                shutil.rmtree(target / name)
    target.mkdir(parents=True, exist_ok=True)
    (target / MARKER).write_text("Written by `loopcaptain demo`; it may clear .loops, work and out here.\n")
    (target / "loops.py").write_text(helper_source(), encoding="utf-8")
    (target / "loop.py").write_text((HERE / "loop.py").read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run(
        [sys.executable, "loop.py", "--seed", str(SEEDED_ROUNDS)],
        cwd=target,
        check=True,
        timeout=SEED_TIMEOUT_S,
    )
    return target
