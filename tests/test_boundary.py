"""One loop, one folder or one config that cannot be read does not take the rest of the board with it."""

from __future__ import annotations

import json
import math
import os
import types
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loopcaptain.board.app import create_app
from loopcaptain.board.discover import Config, find_repos, parse_config
from loopcaptain.board.filters import stamp
from loopcaptain.board.steer import Runner
from loopcaptain.protocol import store
from loopcaptain.protocol.models import now
from loopcaptain.protocol.store import StoreError

HOST = "board.test"
DEPTH = 100_000
NO_ROOT = pytest.mark.skipif(os.geteuid() == 0, reason="root may enter every folder")


def board(config: Config, state: Path) -> TestClient:
    app = create_app(config=lambda: config, runner=Runner(state), allowed_hosts=frozenset({HOST}))
    client = TestClient(app, base_url=f"http://{HOST}", follow_redirects=False, raise_server_exceptions=False)
    client.cookies.set(app.state.session.cookie_name, app.state.session.cookie_value)
    return client


@pytest.fixture
def other(tmp_path: Path, helper: types.ModuleType) -> Path:
    """A second repository beside `some-repo`, with one loop that each test then breaks."""
    path = tmp_path / "other-repo"
    path.mkdir()
    helper.register("odd", {"title": "Odd one"}, path)
    helper.emit("odd", "round_started", {"round": 1}, path)
    return path


@pytest.fixture
def unlock() -> Iterator[list[Path]]:
    """Folders a test locks; opened again afterwards so the temporary folder can be removed."""
    locked: list[Path] = []
    yield locked
    for path in locked:
        path.chmod(0o755)


def assert_the_rest_works(client: TestClient, scan: Path) -> None:
    """The good loop's page, both pulses and its Stop, with another loop or folder broken beside it."""
    overview = client.get("/")
    assert overview.status_code == 200 and "Market scan" in overview.text
    assert client.get("/loop/some-repo/scan").status_code == 200
    assert "pulse" in client.get("/pulse").json()
    assert "pulse" in client.get("/loop/some-repo/scan/pulse").json()
    token = client.app.state.token  # type: ignore[attr-defined]
    stopped = client.post("/loop/some-repo/scan/stop", data={"token": token})
    assert stopped.status_code == 303 and "note=Stop" in stopped.headers["location"]
    assert [entry.kind for entry in store.read_inbox(scan, "scan")[0]] == ["stop"]


def test_a_manifest_nested_deeper_than_can_be_parsed_is_named_and_the_rest_works(
    scan: Path, other: Path, tmp_path: Path
) -> None:
    deep = '{"protocol": 1, "id": "odd", "x": ' + "[" * DEPTH + "]" * DEPTH + "}"
    (other / ".loops" / "odd" / "loop.json").write_text(deep)
    client = board(Config(repos=(scan, other)), tmp_path / "state")

    page = client.get("/").text

    assert "other-repo" in page and "recursion" in page.lower()
    assert client.get("/loop/other-repo/odd").status_code in (200, 404)
    assert_the_rest_works(client, scan)


def test_an_event_nested_deeper_than_can_be_parsed_is_one_unreadable_line(
    scan: Path, other: Path, tmp_path: Path
) -> None:
    line = '{"ts": "2026-11-14T21:00:00+00:00", "event": "round_started", "round": 2, "plan": '
    with (other / ".loops" / "odd" / "events.jsonl").open("a") as handle:
        handle.write(line + "[" * DEPTH + "]" * DEPTH + "}\n")
    client = board(Config(repos=(scan, other)), tmp_path / "state")

    assert "Odd one" in client.get("/").text
    assert client.get("/loop/other-repo/odd").status_code == 200
    assert_the_rest_works(client, scan)


@pytest.mark.parametrize("field", ["next_at", "ts"])
def test_a_time_in_the_year_9999_does_not_break_a_page(
    scan: Path, other: Path, tmp_path: Path, helper: types.ModuleType, field: str
) -> None:
    far = "9999-12-31T23:59:59+00:00"
    event = {"ts": "2026-11-15T08:00:00Z", "event": "round_finished", "round": 1, "verdict": "continue"}
    with (other / ".loops" / "odd" / "events.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps({**event, field: far}) + "\n")  # `ts` too, which the helper sets itself
    client = board(Config(repos=(scan, other)), tmp_path / "state")

    assert "Odd one" in client.get("/").text
    for tab in ("overview", "rounds", "inbox"):
        assert client.get(f"/loop/other-repo/odd?tab={tab}").status_code == 200, tab
    assert_the_rest_works(client, scan)


@pytest.mark.parametrize(
    "extra",
    [
        {"next_at": "9999-12-31T23:59:59-23:59"},
        {"at": "0001-01-01T00:00:00+23:00"},
        {"metrics": [{"name": "score", "value": math.nan, "target": math.inf, "better": "higher"}]},
        {"cost": {"usd": math.inf, "tokens_in": 10**400}},
    ],
)
def test_a_far_year_or_a_number_that_is_not_finite_reads_as_a_done_loop_on_every_page(
    scan: Path, other: Path, tmp_path: Path, helper: types.ModuleType, extra: dict[str, object]
) -> None:
    fields = {key: value for key, value in extra.items() if key != "at"}
    helper.emit("odd", "round_finished", {"round": 1, "verdict": "done", **fields}, other, at=extra.get("at"))
    manifest = other / ".loops" / "odd" / "loop.json"
    manifest.write_text(manifest.read_text().replace('"id"', '"cost_cap_usd": Infinity, "id"', 1))
    client = board(Config(repos=(scan, other)), tmp_path / "state")

    page = client.get("/loop/other-repo/odd")
    assert page.status_code == 200 and 'class="pill done"' in page.text
    assert "inf" not in page.text.lower().replace("info", "") and "nan" not in page.text.lower()
    for tab in ("rounds", "inbox", "checks"):
        assert client.get(f"/loop/other-repo/odd?tab={tab}").status_code == 200, tab
    assert client.get("/?finished=1").status_code == 200
    assert_the_rest_works(client, scan)


def test_a_time_no_local_clock_can_show_is_written_as_the_loop_wrote_it() -> None:
    far = now().replace(year=9999, month=12, day=31, hour=23)
    early = now().replace(year=1, month=1, day=1, hour=0)

    assert stamp(far).startswith("9999-12-31") and stamp(early).startswith("0001-01-01")


@NO_ROOT
def test_a_loops_folder_the_board_may_not_enter_is_named_and_the_rest_works(
    scan: Path, other: Path, tmp_path: Path, unlock: list[Path]
) -> None:
    (other / ".loops").chmod(0o000)
    unlock.append(other / ".loops")
    client = board(Config(repos=(scan, other)), tmp_path / "state")

    page = client.get("/").text

    assert "other-repo" in page and "Permission denied" in page
    assert client.get("/loop/other-repo/odd").status_code == 404
    assert_the_rest_works(client, scan)


@NO_ROOT
def test_a_folder_under_a_root_the_board_may_not_enter_is_named_and_the_rest_works(
    scan: Path, tmp_path: Path, unlock: list[Path]
) -> None:
    sibling = scan.parent / "sealed"
    sibling.mkdir()
    sibling.chmod(0o000)
    unlock.append(sibling)
    config = Config(roots=(scan.parent,))
    client = board(config, tmp_path / "state")

    page = client.get("/").text

    assert [repo.key for repo in find_repos(config)] == ["some-repo"]
    assert "sealed" in page and "Permission denied" in page
    assert_the_rest_works(client, scan)


@NO_ROOT
def test_a_root_the_board_may_not_list_is_named(scan: Path, tmp_path: Path, unlock: list[Path]) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    root.chmod(0o000)
    unlock.append(root)
    client = board(Config(roots=(root,), repos=(scan,)), tmp_path / "state")

    page = client.get("/").text

    assert "vault" in page and "Permission denied" in page
    assert_the_rest_works(client, scan)


def test_a_loop_whose_folding_fails_is_shown_as_unreadable_with_the_reason(
    scan: Path, other: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = store.read_events

    def read_events(repo: Path, loop_id: str) -> object:
        if loop_id == "odd":
            raise OverflowError("date value out of range")
        return real(repo, loop_id)

    monkeypatch.setattr(store, "read_events", read_events)
    client = board(Config(repos=(scan, other)), tmp_path / "state")

    overview = client.get("/").text
    page = client.get("/loop/other-repo/odd")

    assert "unreadable" in overview and "date value out of range" in overview
    assert page.status_code == 200 and "date value out of range" in page.text
    assert_the_rest_works(client, scan)


@pytest.mark.parametrize("content", [b"repos: [\xff\xfe]\n", b'repos: ["a\\0b"]\n', b'roots: ["a\\0b"]\n'])
def test_a_config_of_bytes_that_are_not_text_or_a_path_with_a_null_is_named_not_a_fault(
    scan: Path, tmp_path: Path, content: bytes
) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_bytes(content)
    app = create_app(
        config=lambda: parse_config(config_file),
        runner=Runner(tmp_path / "state"),
        allowed_hosts=frozenset({HOST}),
    )
    client = TestClient(app, base_url=f"http://{HOST}", raise_server_exceptions=False)
    client.cookies.set(app.state.session.cookie_name, app.state.session.cookie_value)

    overview = client.get("/", headers={"accept": "text/html"})
    loop = client.get("/loop/some-repo/scan", headers={"accept": "text/html"})

    assert overview.status_code == 200 and "config.yaml" in overview.text
    assert loop.status_code == 503 and "config.yaml" in loop.text


@pytest.mark.parametrize(
    "path",
    ["/", "/pulse", "/loop/some-repo/scan", "/loop/some-repo/scan/pulse", "/loop/some-repo/scan/file?path=x"],
)
def test_a_config_that_cannot_be_read_gives_a_page_that_says_so(
    scan: Path, tmp_path: Path, path: str
) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("roots: [unclosed\n")
    app = create_app(
        config=lambda: parse_config(config_file),
        runner=Runner(tmp_path / "state"),
        allowed_hosts=frozenset({HOST}),
    )
    client = TestClient(app, base_url=f"http://{HOST}", raise_server_exceptions=False)
    client.cookies.set(app.state.session.cookie_name, app.state.session.cookie_value)

    answer = client.get(path, headers={"accept": "text/html"})
    fetched = client.get(path)
    posted = client.post("/loop/some-repo/scan/stop", data={"token": app.state.token})

    assert 500 not in (answer.status_code, fetched.status_code, posted.status_code)
    assert "config.yaml" in fetched.text or fetched.json() == {"pulse": "error"}
    if "pulse" not in path:
        assert "config.yaml" in answer.text and "<h1>" in answer.text


def test_a_config_nested_past_the_parser_is_named(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("[" * 5000, encoding="utf-8")
    with pytest.raises(StoreError, match=r"config\.yaml"):
        parse_config(config)
