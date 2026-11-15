"""Retake the screenshots from an invented set of loops, light and dark: `make shots`.

Writes the loops of `scripts/showcase.py` into a temporary folder, starts a board on that folder
alone and photographs five pages with headless Chrome: the overview, large, and four smaller views
for a two-by-two grid. Corners are rounded in the picture itself, so they are round wherever it is
shown. Nothing of this machine's own loops can appear: the board reads only the temporary folder,
and the folder stands in for the home folder, so paths read `~/projects/...`. Needs Chrome and
Pillow (`make shots` brings Pillow); costs nothing. `make shots ONLY=connect` retakes the pictures
whose name contains that word and leaves the others as they are.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw
from showcase import write_showcase

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
    picture = Image.open(shot).convert("RGBA")
    mask = Image.new("L", picture.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *picture.size), radius=RADIUS * SCALE, fill=255)
    picture.putalpha(mask)
    return picture


def photograph(path: str, target: Path, height: int, scheme: int) -> None:
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
            f"http://127.0.0.1:{PORT}{path}",
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )


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
        board = subprocess.Popen(
            [sys.executable, "-m", "loopcaptain.cli", "serve", "--port", str(PORT)], env=board_env
        )
        try:
            wait_for(lambda: answers(f"http://127.0.0.1:{PORT}/"), "the board")
            for path, name, height in (page for page in PAGES if only in page[1]):
                for scheme, value in SCHEMES.items():
                    shot = base / f"{name}-{scheme}.png"
                    photograph(path, shot, height, value)
                    webp = ASSETS / f"{name}{'-dark' if scheme == 'dark' else ''}.webp"
                    rounded(shot).save(webp, "WEBP", quality=82, method=6)
                    sys.stdout.write(f"{webp.relative_to(ROOT)}\n")
        finally:
            board.terminate()
            board.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
