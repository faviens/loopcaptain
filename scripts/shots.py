"""Retake the README's screenshots from the example loop, light and dark: `make shots`.

Writes the example loop into a temporary folder, runs it until it asks its question, starts a board
on that folder alone and photographs three pages with headless Chrome. Nothing of this machine's
own loops can appear: the board reads only the temporary folder. Needs Chrome; costs nothing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from loopcaptain.demo import write_demo

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
PORT = 8497
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
WIDTH = 1360
#: Page, file name, height in pixels.
PAGES = (
    ("/?tab=waiting", "screenshot-overview", 1100),
    ("/loop/demo/loop-engineering", "screenshot-loop", 1500),
    ("/loop/demo/loop-engineering?tab=rounds&round=2", "screenshot-rounds", 1700),
)
SCHEMES = {"light": 1, "dark": 0}  # Blink's preferredColorScheme


def wait_for(check: object, what: str, seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if callable(check) and check():
            return
        time.sleep(0.5)
    raise SystemExit(f"shots: gave up waiting for {what}")


def asked(repo: Path) -> bool:
    log = repo / ".loops" / "loop-engineering" / "events.jsonl"
    return log.is_file() and '"event": "question"' in log.read_text()


def answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return bool(response.status == 200)
    except OSError:
        return False


def main() -> int:
    if not Path(CHROME).exists():
        raise SystemExit(f"shots: no Chrome at {CHROME}; set CHROME to its path")
    with tempfile.TemporaryDirectory() as scratch:
        base = Path(scratch)
        repo = write_demo(base / "demo")
        env = {**os.environ, "LOOPCAPTAIN_INBOX_KEY": str(base / "inbox.key")}
        loop = subprocess.Popen(
            [sys.executable, "loop.py", "--rounds", "1", "--pace", "0", "--wait", "300"], cwd=repo, env=env
        )
        (base / "config.yaml").write_text(f"repos:\n  - {repo}\n")
        board_env = {
            **env,
            "LOOPCAPTAIN_CONFIG": str(base / "config.yaml"),
            "LOOPCAPTAIN_STATE": str(base / "s"),
        }
        board = subprocess.Popen(
            [sys.executable, "-m", "loopcaptain.cli", "serve", "--port", str(PORT)], env=board_env
        )
        try:
            wait_for(lambda: asked(repo), "the example loop to ask")
            wait_for(lambda: answers(f"http://127.0.0.1:{PORT}/"), "the board")
            for path, name, height in PAGES:
                for scheme, value in SCHEMES.items():
                    target = base / f"{name}-{scheme}.png"
                    subprocess.run(
                        [
                            CHROME,
                            "--headless=new",
                            "--disable-gpu",
                            "--hide-scrollbars",
                            f"--window-size={WIDTH},{height}",
                            f"--blink-settings=preferredColorScheme={value}",
                            "--force-device-scale-factor=2",
                            f"--screenshot={target}",
                            f"http://127.0.0.1:{PORT}{path}",
                        ],
                        check=True,
                        capture_output=True,
                        timeout=60,
                    )
                    webp = ASSETS / f"{name}{'-dark' if scheme == 'dark' else ''}.webp"
                    subprocess.run(["cwebp", "-quiet", "-q", "82", str(target), "-o", str(webp)], check=True)
                    sys.stdout.write(f"{webp.relative_to(ROOT)}\n")
        finally:
            board.terminate()
            loop.terminate()
            board.wait(timeout=10)
            loop.wait(timeout=10)
    return 0


if __name__ == "__main__":
    if shutil.which("cwebp") is None:
        raise SystemExit("shots: needs cwebp (brew install webp) to write .webp files")
    raise SystemExit(main())
