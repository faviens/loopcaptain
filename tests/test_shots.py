"""`make shots` opens every page through the address `serve` prints, so the board lets Chrome in."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loopcaptain.board.app import create_app, entry_address
from loopcaptain.board.discover import Config
from loopcaptain.board.steer import Runner

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOST = "127.0.0.1:8497"


@pytest.fixture(scope="module")
def shots() -> types.ModuleType:
    sys.path.insert(0, str(SCRIPTS))  # shots imports showcase from its own folder, as `make shots` runs it
    try:
        spec = importlib.util.spec_from_file_location("shots", SCRIPTS / "shots.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


@pytest.fixture
def board(scan: Path, tmp_path: Path) -> TestClient:
    app = create_app(
        config=lambda: Config(repos=(scan,)),
        runner=Runner(tmp_path / "state"),
        allowed_hosts=frozenset({HOST}),
    )
    return TestClient(app, base_url=f"http://{HOST}", follow_redirects=False)


def test_the_entry_is_read_from_the_line_serve_prints(shots: types.ModuleType, board: TestClient) -> None:
    entry = entry_address(8497, board.app.state.session)  # type: ignore[attr-defined]
    printed = f"open {entry}   (1 repository with loops, config: ~/config.yaml)\n"

    assert shots.entry_of(printed) == entry
    assert shots.entry_of("") is None
    assert shots.entry_of("INFO uvicorn: started\n") is None


def test_every_page_of_the_shots_is_reached_through_the_entry_of_its_own_board(
    shots: types.ModuleType, scan: Path, tmp_path: Path
) -> None:
    """Each shot is a new headless Chrome without a cookie, and an address lets one browser in, so
    every shot has a board, and an address, of its own."""
    for path, _, _ in shots.PAGES:
        app = create_app(
            config=lambda: Config(repos=(scan,)),
            runner=Runner(tmp_path / "state"),
            allowed_hosts=frozenset({HOST}),
        )
        chrome = TestClient(app, base_url=f"http://{HOST}", follow_redirects=False)
        entry = entry_address(8497, app.state.session)

        answer = chrome.get(shots.page_address(entry, path))

        assert answer.status_code == 303, path
        assert answer.headers["location"] == path
        assert "loopcaptain" in answer.headers.get("set-cookie", "")
