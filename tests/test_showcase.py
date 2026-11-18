"""The invented loops of the screenshots follow the protocol, and the overview marks what needs a look."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loopcaptain.board.app import create_app
from loopcaptain.board.discover import Config
from loopcaptain.board.steer import Runner
from loopcaptain.protocol.validate import validate_loop

ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1:8484"


@pytest.fixture(scope="module")
def showcase() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("showcase", ROOT / "scripts" / "showcase.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while it is being defined
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repos(showcase: types.ModuleType, tmp_path: Path) -> list[Path]:
    written: list[Path] = showcase.write_showcase(tmp_path / "projects", datetime.now(UTC))
    return written


def test_every_invented_loop_follows_the_protocol(showcase: types.ModuleType, repos: list[Path]) -> None:
    for show in showcase.SHOWS:
        report = validate_loop(repos[0].parent / show.repo, show.loop)

        assert report.problems == [], (show.loop, report.problems)


def test_the_overview_marks_what_waits_what_runs_and_what_is_stuck(repos: list[Path], tmp_path: Path) -> None:
    app = create_app(
        config=lambda: Config(repos=tuple(repos)),
        runner=Runner(tmp_path / "state"),
        allowed_hosts=frozenset({HOST}),
    )

    client = TestClient(app, base_url=f"http://{HOST}")
    client.cookies.set(app.state.session.cookie_name, app.state.session.issue() or "")

    page = client.get("/?finished=1").text

    assert 'class="kpi hot"><b>1</b>' in page
    assert 'class="kpi live"><b>3</b>' in page  # running and sleeping are one group
    assert (
        'class="kpi alarm" title="stalled, failed or capped, or going round without progress"><b>3</b><span>need a look'
        in page
    )
    for status in ("waiting", "running", "stalled", "failed", "sleeping", "done", "capped"):
        assert f'<tr class="is-{status}">' in page, status
