"""The start command as the board reads it: what it splits into, and what it refuses to run."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loopcaptain.board.app import create_app
from loopcaptain.board.command import read_command
from loopcaptain.board.discover import Config
from loopcaptain.board.steer import Runner
from loopcaptain.protocol import store

HOST = "board.test"
#: U+202E turns the reading direction: the text after it is drawn right to left.
OVERRIDE = "\u202e"
NO_BREAK_SPACE = "\u00a0"
ZERO_WIDTH_SPACE = "\u200b"


@pytest.fixture
def client(scan: Path, tmp_path: Path) -> TestClient:
    app = create_app(
        config=lambda: Config(repos=(scan,)),
        runner=Runner(tmp_path / "state"),
        allowed_hosts=frozenset({HOST}),
    )
    client = TestClient(app, base_url=f"http://{HOST}", follow_redirects=False)
    session = app.state.session
    client.cookies.set(session.cookie_name, session.issue() or "")
    return client


def declare(repo: Path, helper: types.ModuleType, command: str) -> None:
    helper.register("scan", {"title": "Market scan", "commands": {"start": command}}, repo)


def start(client: TestClient, repo: Path) -> str:
    form = {
        "token": str(client.app.state.token),  # type: ignore[attr-defined]
        "command": store.read_manifest(repo, "scan").commands["start"],
        "confirm": "yes",
        "again": "yes",
    }
    return client.post("/loop/some-repo/scan/start", data=form).headers["location"]


@pytest.mark.parametrize(
    ("hidden", "name"),
    [
        (OVERRIDE, "U+202E"),
        (ZERO_WIDTH_SPACE, "U+200B"),
        (NO_BREAK_SPACE, "U+00A0"),
        ("\t", "U+0009"),
        ("\x1b", "U+001B"),
    ],
)
def test_a_command_with_a_character_that_does_not_show_is_named_and_not_read(hidden: str, name: str) -> None:
    command = read_command(f"python3 loop.py{hidden}--rounds 2")

    assert name in command.problem and command.argv == ()
    assert hidden not in command.shown and f"<{name}>" in command.shown


def test_a_plain_command_splits_into_the_arguments_that_run() -> None:
    command = read_command(' python3 loop.py --note "two words" ')

    assert command.problem == "" and command.shown == command.text
    assert command.argv == ("python3", "loop.py", "--note", "two words")


def test_a_command_that_reads_as_another_is_marked_on_the_page_and_never_started(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    script = "open('ran.txt', 'w').write('x')"
    declare(scan, helper, f'{sys.executable} -c "{script}" {OVERRIDE}yp.pool')

    page = client.get("/loop/some-repo/scan").text
    answer = start(client, scan)

    assert "&lt;U+202E&gt;" in page and "Not started from here" in page
    assert 'form="start-loop"' not in page and 'name="confirm"' not in page
    assert "do%20not%20show" in answer and not (scan / "ran.txt").exists()


def test_the_page_lists_the_arguments_a_command_runs_as(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    declare(scan, helper, 'python3 loop.py --note "two words"')

    page = client.get("/loop/some-repo/scan").text

    assert "It runs as 4 arguments, without a shell" in page
    assert "<li><code>two words</code></li>" in page and 'form="start-loop"' in page
