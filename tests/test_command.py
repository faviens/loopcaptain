"""The start command as the board reads it: what it splits into, and what it refuses to run."""

from __future__ import annotations

import sys
import time
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loopcaptain.board.app import create_app
from loopcaptain.board.command import named_files, read_command
from loopcaptain.board.discover import Config, find_repos
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
    """Press Start with every tick, and wait for the process to end: a second start is refused
    while the first still runs."""
    form = {
        "token": str(client.app.state.token),  # type: ignore[attr-defined]
        "command": store.read_manifest(repo, "scan").commands["start"],
        "confirm": "yes",
        "again": "yes",
    }
    location = str(client.post("/loop/some-repo/scan/start", data=form).headers["location"])
    for _ in range(200):
        if "Running since" not in client.get("/loop/some-repo/scan").text:
            return location
        time.sleep(0.05)
    raise AssertionError("the started process did not end")


@pytest.mark.parametrize(
    ("hidden", "name"),
    [
        (OVERRIDE, "U+202E"),
        (ZERO_WIDTH_SPACE, "U+200B"),
        (NO_BREAK_SPACE, "U+00A0"),
        ("\t", "U+0009"),
        ("\x1b", "U+001B"),
        ("\u3164", "U+3164"),  # a Hangul filler: a letter that is drawn as a blank
        ("\u2800", "U+2800"),  # the empty braille pattern
        ("\ufe0f", "U+FE0F"),  # a variation selector
        ("\u034f", "U+034F"),  # the combining grapheme joiner
        ("\U000e0101", "U+E0101"),
        ("\u0378", "U+0378"),  # assigned to nothing
    ],
)
def test_a_command_with_a_character_that_does_not_show_is_named_and_not_read(hidden: str, name: str) -> None:
    command = read_command(f"python3 loop.py{hidden}--rounds 2")

    assert name in command.problem and command.argv == ()
    assert hidden not in command.shown and f"<{name}>" in command.shown


def test_letters_and_marks_that_show_are_not_refused() -> None:
    command = read_command("python3 r\u00e9sum\u00e9/e\u0301t\u00e9.py \u65e5\u672c \u0915\u093f")

    assert command.problem == "" and len(command.argv) == 4


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


def test_a_tick_covers_one_loop_and_a_second_loop_with_the_same_command_asks_again(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    command = f"{sys.executable} -c pass"
    declare(scan, helper, command)
    helper.register("other", {"title": "Other", "commands": {"start": command}}, scan)
    start(client, scan)

    first, second = client.get("/loop/some-repo/scan").text, client.get("/loop/some-repo/other").text
    form = {"token": str(client.app.state.token), "command": command}  # type: ignore[attr-defined]
    refused = client.post("/loop/some-repo/other/start", data=form).headers["location"]

    assert 'name="confirm"' not in first and 'name="confirm"' in second
    assert "first%20start" in refused


def test_the_page_names_a_script_that_changed_since_the_board_last_started_it(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    (scan / "loop.py").write_text("pass\n")
    declare(scan, helper, f"{sys.executable} loop.py")
    untouched_before = client.get("/loop/some-repo/scan").text
    start(client, scan)
    untouched_after = client.get("/loop/some-repo/scan").text

    (scan / "loop.py").write_text("import shutil\n")
    changed = client.get("/loop/some-repo/scan").text
    start(client, scan)
    started_again = client.get("/loop/some-repo/scan").text

    marker = "Changed since the board last started this command"
    assert marker not in untouched_before and marker not in untouched_after
    assert marker in changed and "path=loop.py" in changed
    assert marker not in started_again


def test_only_files_the_board_would_show_are_read_for_a_command(scan: Path, tmp_path: Path) -> None:
    (scan / "loop.py").write_text("pass\n")
    (scan / ".env").write_text("KEY=1\n")
    (scan / "tool.bin").write_bytes(b"\x00\x01")
    (tmp_path / "outside.py").write_text("pass\n")

    found = named_files(
        scan, ("python3", "loop.py", ".env", "tool.bin", "../outside.py", "no-such.py", "\x00")
    )

    assert list(found) == ["loop.py"]


def test_a_list_of_ticks_kept_by_an_older_board_reads_as_none(scan: Path, tmp_path: Path) -> None:
    runner = Runner(tmp_path / "state")
    runner.state_dir.mkdir()
    (runner.state_dir / "confirmed.json").write_text('["abc"]\n')
    repo = find_repos(Config(repos=(scan,)))[0]

    assert runner.confirmed() == {} and runner.changed_files(repo, "scan", "x") == []
