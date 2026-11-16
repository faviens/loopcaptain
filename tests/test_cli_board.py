"""The board's commands on the command line: `serve`, `watch`, `unwatch` and `demo` say where things are."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

import pytest
import uvicorn

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


def test_the_board_listens_on_this_machine_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, served: list[dict[str, Any]]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    port = free_port()

    cli_main(["serve", "--port", str(port)])

    assert [(call["host"], call["port"]) for call in served] == [("127.0.0.1", port)]


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
