"""The board's commands on the command line: `serve`, `watch`, `unwatch` and `demo` say where things are."""

from __future__ import annotations

import ast
import socket
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from loopcaptain import cli
from loopcaptain.board.discover import Config, parse_config
from loopcaptain.cli import main as cli_main


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every call that would have started the server, which never starts."""
    calls: list[dict[str, Any]] = []

    def run(app: object, *, host: str, port: int, log_level: str) -> None:
        calls.append({"app": app, "host": host, "port": port})

    monkeypatch.setattr(uvicorn, "run", run)
    return calls


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_serve_says_in_one_line_where_the_board_is_and_what_it_watches(
    scan: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    served: list[dict[str, Any]],
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(f"repos:\n  - {scan}\n")
    monkeypatch.setenv("LOOPCAPTAIN_CONFIG", str(config))
    port = free_port()

    assert cli_main(["serve", "--port", str(port)]) == 0

    out = capsys.readouterr().out
    key = served[0]["app"].state.session.key
    assert out.count("\n") == 1
    assert f"open http://127.0.0.1:{port}/enter?key={key}" in out
    assert "1 repository with loops" in out and "config.yaml" in out


def test_serve_makes_the_inbox_key_before_the_board_opens(
    tmp_path: Path, inbox_key: Path, monkeypatch: pytest.MonkeyPatch, served: list[dict[str, Any]]
) -> None:
    """From its first minute a loop can tell the board's lines from any other: the key is there."""
    monkeypatch.setenv("LOOPCAPTAIN_CONFIG", str(tmp_path / "none.yaml"))

    assert not inbox_key.exists()
    cli_main(["serve", "--port", str(free_port())])

    assert inbox_key.is_file() and served


def test_the_board_listens_on_this_machine_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, served: list[dict[str, Any]]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    port = free_port()

    cli_main(["serve", "--port", str(port)])

    assert [(call["host"], call["port"]) for call in served] == [("127.0.0.1", port)]


def test_the_served_board_answers_to_its_own_address_and_no_other_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, served: list[dict[str, Any]]
) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    port = free_port()
    cli_main(["serve", "--port", str(port)])
    client = TestClient(served[0]["app"])

    codes = {
        host: client.get("/static/mark.svg", headers={"host": host}).status_code
        for host in (f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", f"other.example:{port}", "")
    }

    assert codes == {
        f"127.0.0.1:{port}": 200,
        f"localhost:{port}": 200,
        "127.0.0.1": 400,
        f"other.example:{port}": 400,
        "": 400,
    }


def test_serve_without_a_config_says_so(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    served: list[dict[str, Any]],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("LOOPCAPTAIN_CONFIG", raising=False)

    cli_main(["serve", "--port", str(free_port())])

    assert "0 repositories with loops, config: no config file" in capsys.readouterr().out


def test_a_taken_port_is_one_line_and_no_server(
    capsys: pytest.CaptureFixture[str], served: list[dict[str, Any]]
) -> None:
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]

        code = cli_main(["serve", "--port", str(port)])

    said = capsys.readouterr()
    assert code == 1 and served == [] and said.out == ""
    assert said.err.count("\n") == 1 and f"port {port}" in said.err and "--port" in said.err
    assert "Traceback" not in said.err


def test_a_number_that_is_no_port_is_one_line_too(
    capsys: pytest.CaptureFixture[str], served: list[dict[str, Any]]
) -> None:
    assert cli_main(["serve", "--port", "99999"]) == 1
    assert served == [] and "port 99999" in capsys.readouterr().err


def test_the_demo_says_how_to_start_the_board_from_where_it_was_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    cli_main(["demo", "--target", str(tmp_path / "demo"), "--no-watch"])
    installed = capsys.readouterr().out
    (tmp_path / "Makefile").write_text("serve:\n")
    cli_main(["demo", "--target", str(tmp_path / "demo"), "--no-watch"])
    checkout = capsys.readouterr().out

    assert "`loopcaptain serve` and open the address it prints" in installed
    assert "`make serve` and open the address it prints" in checkout
    assert "8484" not in installed + checkout


def test_the_demo_run_through_uvx_says_to_start_the_board_through_uvx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UV", "uv")
    monkeypatch.setattr("sys.prefix", str(tmp_path / "cache" / "archive-v0" / "a1b2"))

    cli_main(["demo", "--target", str(tmp_path / "demo"), "--no-watch"])

    assert "`uvx loopcaptain serve` and open the address it prints" in capsys.readouterr().out


# ---- a wrong path says so ----


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home folder and a working folder of the test's own, with no config named."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("LOOPCAPTAIN_CONFIG", raising=False)
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    return tmp_path / "home"


def test_a_named_config_that_is_missing_is_an_error_not_another_config(
    scan: Path,
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    served: list[dict[str, Any]],
) -> None:
    from loopcaptain.board.discover import load_config
    from loopcaptain.protocol.store import StoreError

    (home / ".config" / "loopcaptain").mkdir(parents=True)
    (home / ".config" / "loopcaptain" / "config.yaml").write_text(f"repos:\n  - {scan}\n")
    fallback = load_config()
    monkeypatch.setenv("LOOPCAPTAIN_CONFIG", str(tmp_path / "mistyped.yaml"))

    with pytest.raises(StoreError, match=r"LOOPCAPTAIN_CONFIG names .*mistyped\.yaml, which is not a file"):
        load_config()
    cli_main(["serve", "--port", str(free_port())])

    assert fallback.repos == (scan.resolve(),)
    assert "mistyped.yaml, which is not a file" in capsys.readouterr().out


def test_the_board_says_on_its_first_page_that_the_named_config_is_missing(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from loopcaptain.board.app import create_app
    from loopcaptain.board.steer import Runner

    monkeypatch.setenv("LOOPCAPTAIN_CONFIG", str(tmp_path / "mistyped.yaml"))
    app = create_app(runner=Runner(tmp_path / "state"), allowed_hosts=frozenset({"board.test"}))
    client = TestClient(app, base_url="http://board.test")
    client.cookies.set(app.state.session.cookie_name, app.state.session.issue() or "")

    page = client.get("/")

    assert page.status_code == 200 and "mistyped.yaml, which is not a file" in page.text


def test_watch_names_the_config_it_wrote(scan: Path, home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main(["watch", str(scan)]) == 0

    out = capsys.readouterr().out
    assert str(home / ".config" / "loopcaptain" / "config.yaml") in out and "added" in out
    assert "warning" not in out


def test_watch_warns_when_the_board_started_here_reads_another_config(
    scan: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    Path("loopcaptain.local.yaml").write_text("repos: []\n")

    assert cli_main(["watch", str(scan)]) == 0

    out = capsys.readouterr().out
    assert "warning: a board started in this folder reads" in out and "loopcaptain.local.yaml" in out


def test_watch_refuses_a_folder_that_does_not_exist_and_writes_nothing(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli_main(["watch", str(tmp_path / "nowhere")]) == 1

    assert "is not a folder; nothing was written" in capsys.readouterr().err
    assert not (home / ".config" / "loopcaptain" / "config.yaml").exists()


@pytest.mark.parametrize(
    ("flags", "words"), [([], "it has no `.loops/` folder"), (["--root"], "no sub-folder of it has")]
)
def test_watch_warns_about_a_folder_without_loops(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], flags: list[str], words: str
) -> None:
    (tmp_path / "empty").mkdir()

    assert cli_main(["watch", *flags, str(tmp_path / "empty")]) == 0

    out = capsys.readouterr().out
    assert "added" in out and f"warning: {words}" in out


def test_watch_with_root_finds_the_loops_one_level_down_and_does_not_warn(
    scan: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli_main(["watch", "--root", str(scan.parent)]) == 0

    assert "warning" not in capsys.readouterr().out


def test_the_demo_warns_when_the_board_started_here_would_not_show_it(
    scan: Path, home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli_main(["demo", "--target", str(tmp_path / "demo"), "--no-watch"])
    quiet = capsys.readouterr().out
    (home / ".config" / "loopcaptain").mkdir(parents=True)
    (home / ".config" / "loopcaptain" / "config.yaml").write_text(f"repos:\n  - {scan}\n")
    cli_main(["demo", "--target", str(tmp_path / "demo"), "--no-watch"])
    warned = capsys.readouterr().out

    assert "warning" not in quiet
    assert "which does not list" in warned and "loopcaptain watch" in warned


def test_the_empty_board_names_the_config_it_read(home: Path, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from loopcaptain.board.app import create_app
    from loopcaptain.board.steer import Runner

    (tmp_path / "empty").mkdir()
    Path("loopcaptain.local.yaml").write_text(f"repos:\n  - {tmp_path / 'empty'}\n")
    app = create_app(runner=Runner(tmp_path / "state"), allowed_hosts=frozenset({"board.test"}))
    client = TestClient(app, base_url="http://board.test")
    client.cookies.set(app.state.session.cookie_name, app.state.session.issue() or "")

    listed = client.get("/").text
    Path("loopcaptain.local.yaml").unlink()
    nothing = client.get("/").text

    assert "work/loopcaptain.local.yaml</code>" in listed and "none of the 1 folder it lists" in listed
    assert "found no <code>loopcaptain.local.yaml</code>" in nothing


def test_every_command_has_a_function_of_its_own_and_none_is_long() -> None:
    """One function per command: a new command adds a function, it does not lengthen one."""
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    lengths = {
        node.name: (node.end_lineno or node.lineno) - node.lineno + 1
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name != "build_parser"
    }
    choices = cli.build_parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]

    assert {name: length for name, length in lengths.items() if length > 50} == {}
    assert set(cli.COMMANDS) == set(choices or {})


@pytest.mark.parametrize(
    "command",
    [
        ["demo", "--no-watch", "--target", "{locked}/demo"],
        ["schema", "{locked}/schema"],
        ["emit", "scan", "round_started", "round=3", "--repo", "{locked}"],
        ["watch", "{folder}"],
    ],
)
def test_a_folder_that_cannot_be_written_is_one_line_not_a_traceback(
    command: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    locked, folder = tmp_path / "locked", tmp_path / "folder"
    (locked / ".loops" / "scan").mkdir(parents=True)
    (locked / ".loops" / "scan" / "loop.json").write_text('{"protocol": 1, "id": "scan"}')
    folder.mkdir()
    monkeypatch.setenv("LOOPCAPTAIN_CONFIG", str(locked / "config.yaml"))
    for path in (locked / ".loops" / "scan", locked):
        path.chmod(0o500)

    try:
        code = cli_main([part.format(locked=locked, folder=folder) for part in command])
    finally:
        for path in (locked, locked / ".loops" / "scan"):
            path.chmod(0o700)

    err = capsys.readouterr().err
    assert code == 1 and err.startswith("loopcaptain: ") and err.count("\n") == 1
    assert "Traceback" not in err and "ermission" in err


def test_watch_and_unwatch_keep_the_comments_and_the_other_lines_of_a_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, first, second = tmp_path / "config.yaml", tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    written = f"# what the board shows\nroots: []  # none yet\nrepos:\n    - {first}  # the scan\n\n# end\n"
    config.write_text(written)
    monkeypatch.setenv("LOOPCAPTAIN_CONFIG", str(config))

    assert cli_main(["watch", str(second)]) == 0 and cli_main(["watch", str(second), "--root"]) == 0
    added = config.read_text()
    assert cli_main(["unwatch", str(second)]) == 0

    assert added == (
        f"# what the board shows\nroots:  # none yet\n  - {second}\nrepos:\n    - {first}  # the scan\n"
        f"    - {second}\n\n# end\n"
    )
    assert config.read_text() == written.replace("roots: []  # none yet", "roots:  # none yet")
    assert parse_config(config) == Config(repos=(first.resolve(),), source=config)


def test_unwatch_finds_an_entry_by_the_folder_it_names_however_it_was_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config, folder = tmp_path / "config.yaml", tmp_path / "work" / "tool"
    folder.mkdir(parents=True)
    config.write_text("repos:\n  - work/tool/   # relative to this file, with a slash\n  - work/other\n")
    monkeypatch.setenv("LOOPCAPTAIN_CONFIG", str(config))

    assert cli_main(["watch", str(folder)]) == 0
    assert "already under repos" in capsys.readouterr().out
    assert cli_main(["unwatch", str(folder)]) == 0

    assert config.read_text() == "repos:\n  - work/other\n"
    assert "removed work/tool/ from repos" in capsys.readouterr().out


def test_a_list_written_on_one_line_is_still_edited_and_other_settings_stay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, first, second = tmp_path / "config.yaml", tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    config.write_text(f"repos: [{first}]\nlater: kept\n")
    monkeypatch.setenv("LOOPCAPTAIN_CONFIG", str(config))

    assert cli_main(["watch", str(second)]) == 0

    assert parse_config(config).repos == (first.resolve(), second.resolve())
    assert "later: kept" in config.read_text()


def test_a_config_that_cannot_be_read_is_one_line_and_is_left_as_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("roots: [unclosed\n")
    monkeypatch.setenv("LOOPCAPTAIN_CONFIG", str(config))

    assert cli_main(["watch", str(tmp_path)]) == 1 and cli_main(["unwatch", str(tmp_path)]) == 1

    err = capsys.readouterr().err
    assert err.count("loopcaptain: ") == 2 and "nothing was written" in err and "Traceback" not in err
    assert config.read_text() == "roots: [unclosed\n"


def test_a_config_is_written_beside_its_place_and_moved_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A write that fails half-way must leave the config a person wrote as it was."""
    config, folder = tmp_path / "config.yaml", tmp_path / "folder"
    folder.mkdir()
    config.write_text("# mine\nrepos: []\n")
    monkeypatch.setenv("LOOPCAPTAIN_CONFIG", str(config))

    def fails(source: object, target: object) -> None:
        raise OSError(28, "No space left on device", str(target))

    monkeypatch.setattr("loopcaptain.board.discover.os.replace", fails)

    assert cli_main(["watch", str(folder)]) == 1
    assert config.read_text() == "# mine\nrepos: []\n" and "No space left" in capsys.readouterr().err
