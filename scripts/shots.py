"""Retake the screenshots from an invented set of loops, light and dark: `make shots`.

Writes the loops of `scripts/showcase.py` into a temporary folder, starts a board on that folder
alone and photographs five pages with headless Chrome: the overview, large, and four smaller views
for a two-by-two grid. Corners are rounded in the picture itself, so they are round wherever it is
shown. Nothing of this machine's own loops can appear: the board reads only the temporary folder,
and the folder stands in for the home folder, so paths read `~/projects/...`. Each page is opened
through the address `serve` prints, so Chrome gets the board's cookie. Needs Chrome and
Pillow (`make shots` brings Pillow); costs nothing. `make shots ONLY=connect` retakes the pictures
whose name contains that word and leaves the others as they are.
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from showcase import write_showcase

if TYPE_CHECKING:
    from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
PORT = 8497
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
WIDTH = 1360
SCALE = 2
#: Corner radius in page pixels; the picture is twice as large.
RADIUS = 18
TILE_HEIGHT = 960
#: Page, file name, height in page pixels. The first is the large picture, the rest the grid.
PAGES = (
    ("/?finished=1", "screenshot-overview", 1430),
    ("/?tab=waiting", "screenshot-waiting", TILE_HEIGHT),
    ("/loop/checkout-service/coverage", "screenshot-loop", TILE_HEIGHT),
    ("/loop/pricing-research/tracker-scan?tab=rounds&round=3", "screenshot-rounds", TILE_HEIGHT),
    ("/loop/pricing-research/tracker-scan?tab=findings", "screenshot-findings", TILE_HEIGHT),
    ("/connect?agent=claude-code", "screenshot-connect", TILE_HEIGHT),
)
SCHEMES = {"light": 1, "dark": 0}  # Blink's preferredColorScheme
#: The one line `serve` prints before it serves: `open <address>   (<what it watches>)`.
SERVE_LINE = re.compile(r"^open (http://\S+/enter\?key=\S+)")


def entry_of(printed: str) -> str | None:
    """The address that lets a browser in, from what `serve` printed so far, or None before it."""
    for line in printed.splitlines():
        found = SERVE_LINE.match(line)
        if found:
            return found.group(1)
    return None


def page_address(entry: str, path: str) -> str:
    """An address that lets the browser in and leads on to `path` on the same board."""
    return f"{entry}&next={quote(path, safe='')}"


def wait_for(check: object, what: str, seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if callable(check) and check():
            return
        time.sleep(0.5)
    raise SystemExit(f"shots: gave up waiting for {what}")


def answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return bool(response.status == 200)
    except OSError:
        return False


def rounded(shot: Path) -> Image.Image:
    """The screenshot with round, transparent corners."""
    from PIL import Image, ImageDraw

    picture = Image.open(shot).convert("RGBA")
    mask = Image.new("L", picture.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *picture.size), radius=RADIUS * SCALE, fill=255)
    picture.putalpha(mask)
    return picture


def photograph(address: str, target: Path, height: int, scheme: int) -> None:
    subprocess.run(
        [
            CHROME,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--window-size={WIDTH},{height}",
            f"--blink-settings=preferredColorScheme={scheme}",
            f"--force-device-scale-factor={SCALE}",
            f"--screenshot={target}",
            address,
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )


@contextlib.contextmanager
def served_board(base: Path, env: dict[str, str]) -> Iterator[str]:
    """A board on PORT for one shot: yields the address it prints, stops it afterwards."""
    printed = base / "serve.out"
    with printed.open("w") as out:
        board = subprocess.Popen(
            [sys.executable, "-m", "loopcaptain.cli", "serve", "--port", str(PORT)],
            env=env,
            stdout=out,
        )
    try:
        wait_for(lambda: entry_of(printed.read_text()) is not None, "the address serve prints")
        entry = entry_of(printed.read_text()) or ""
        wait_for(lambda: answers(entry.split("/enter")[0] + "/static/board.js"), "the board")
        yield entry
    finally:
        board.terminate()
        board.wait(timeout=10)


def main(only: str = "") -> int:
    if not Path(CHROME).exists():
        raise SystemExit(f"shots: no Chrome at {CHROME}; set CHROME to its path")
    with tempfile.TemporaryDirectory() as scratch:
        base = Path(scratch).resolve()  # the board resolves paths, and `~` must match what it sees
        repos = write_showcase(base / "projects", datetime.now(UTC))
        (base / "config.yaml").write_text("repos:\n" + "".join(f"  - {repo}\n" for repo in repos))
        board_env = {
            **os.environ,
            "HOME": str(base),
            "LOOPCAPTAIN_CONFIG": str(base / "config.yaml"),
            "LOOPCAPTAIN_STATE": str(base / "s"),
            "LOOPCAPTAIN_INBOX_KEY": str(base / "inbox.key"),
        }
        for path, name, height in (page for page in PAGES if only in page[1]):
            for scheme, value in SCHEMES.items():
                shot = base / f"{name}-{scheme}.png"
                # Each shot is a new browser, and the printed address lets one browser in.
                with served_board(base, board_env) as entry:
                    photograph(page_address(entry, path), shot, height, value)
                webp = ASSETS / f"{name}{'-dark' if scheme == 'dark' else ''}.webp"
                rounded(shot).save(webp, "WEBP", quality=82, method=6)
                sys.stdout.write(f"{webp.relative_to(ROOT)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
