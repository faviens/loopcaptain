"""Who the board answers: only a browser that opened the address `serve` printed."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from loopcaptain.board.access import Session, is_open, local_path
from loopcaptain.board.app import create_app, entry_address, session_for
from loopcaptain.board.discover import Config
from loopcaptain.board.steer import Runner
from loopcaptain.protocol import store

HOST = "board.test"
PARTS = {"repo_key": "some-repo", "loop_id": "scan"}


@pytest.fixture
def stranger(scan: Path, tmp_path: Path) -> TestClient:
    """A client that never opened the printed address."""
    (scan / "notes.md").write_text("# Plan\n")
    app = create_app(
        config=lambda: Config(repos=(scan,)),
        runner=Runner(tmp_path / "state"),
        allowed_hosts=frozenset({HOST}),
    )
    return TestClient(app, base_url=f"http://{HOST}", follow_redirects=False)


def session_of(client: TestClient) -> Session:
    session: Session = client.app.state.session  # type: ignore[attr-defined]
    return session


def routes_of(client: TestClient) -> list[tuple[str, str]]:
    """Every method and address the app routes, the entry excepted."""
    found: list[tuple[str, str]] = []
    for route in client.app.routes:  # type: ignore[attr-defined]
        if isinstance(route, APIRoute) and route.name != "enter":
            path = re.sub(r"\{(\w+)\}", lambda match: PARTS[match.group(1)], route.path)
            found.extend((method, path) for method in sorted(route.methods or ()))
    return found


def test_every_route_refuses_a_browser_that_was_not_let_in(stranger: TestClient, scan: Path) -> None:
    token = stranger.app.state.token  # type: ignore[attr-defined]
    routes = routes_of(stranger)

    for method, path in routes:
        answer = stranger.request(
            method, path, params={"path": "notes.md"}, data={"token": token, "text": "hello"}
        )

        assert answer.status_code == 401, (method, path)
        assert "Open the board from its own address" in answer.text, (method, path)
        assert "Market scan" not in answer.text and "Plan" not in answer.text
    assert {path for _, path in routes} >= {
        "/",
        "/pulse",
        "/connect",
        "/connect/LOOPS.md",
        "/loop/some-repo/scan",
        "/loop/some-repo/scan/pulse",
        "/loop/some-repo/scan/file",
        "/loop/some-repo/scan/reply",
        "/loop/some-repo/scan/stop",
        "/loop/some-repo/scan/start",
        "/loop/some-repo/scan/kill",
    }
    assert store.read_inbox(scan, "scan") == ([], [])


def test_an_address_that_is_no_route_is_refused_the_same_way(stranger: TestClient) -> None:
    assert stranger.get("/nothing/here").status_code == 401
    assert stranger.post("/enter", data={"key": session_of(stranger).key}).status_code == 405


@pytest.mark.parametrize(
    "path", ["/enterx", "/enter/", "/enter/x", "/entered", "/static", "/staticx/board.css", "/staticx/../"]
)
def test_an_address_that_only_begins_like_an_open_one_is_refused(stranger: TestClient, path: str) -> None:
    assert not is_open(path)
    assert stranger.get(path).status_code == 401


def test_the_stylesheet_and_the_script_are_open_so_the_refusal_can_be_drawn(stranger: TestClient) -> None:
    assert stranger.get("/static/style.css").status_code == 200
    assert stranger.get("/static/board.js").status_code == 200


def test_the_printed_address_lets_the_browser_in_and_leads_to_the_clean_address(
    stranger: TestClient,
) -> None:
    entered = stranger.get(session_of(stranger).entry_path)

    cookie = entered.headers["set-cookie"].lower()
    assert entered.status_code == 303 and entered.headers["location"] == "/"
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    assert "max-age" not in cookie and "expires" not in cookie
    assert stranger.get("/").status_code == 200
    assert "Market scan" in stranger.get("/loop/some-repo/scan").text


def test_the_entry_may_lead_on_to_a_page_of_the_board_and_nowhere_else(stranger: TestClient) -> None:
    path = session_of(stranger).entry_path

    assert stranger.get(f"{path}&next=/connect").headers["location"] == "/connect"
    assert stranger.get(f"{path}&next=//other.example/").headers["location"] == "/"
    assert stranger.get(f"{path}&next=https://other.example/").headers["location"] == "/"
    assert (
        local_path("/\\other.example") == "/" and local_path("/loop/a/b?tab=rounds") == "/loop/a/b?tab=rounds"
    )


@pytest.mark.parametrize("key", ["", "guess", "ü"])
def test_a_wrong_key_lets_nobody_in(stranger: TestClient, key: str) -> None:
    refused = stranger.get("/enter", params={"key": key})

    assert refused.status_code == 401 and "set-cookie" not in refused.headers
    assert stranger.get("/").status_code == 401


def test_a_cookie_from_an_earlier_start_is_refused(stranger: TestClient) -> None:
    earlier = Session()
    stranger.cookies.set(earlier.cookie_name, earlier.cookie_value)

    refused = stranger.get("/")

    assert refused.status_code == 401 and "new key" in refused.text


def test_the_key_is_not_the_cookie_and_appears_on_no_page(stranger: TestClient) -> None:
    session = session_of(stranger)
    refusal = stranger.get("/").text
    stranger.get(session.entry_path)
    pages = [
        stranger.request(method, path, params={"path": "notes.md"}) for method, path in routes_of(stranger)
    ]

    assert session.key != session.cookie_value and session.key not in repr(session)
    for page in [*pages, stranger.get("/static/board.js")]:
        assert session.key not in page.text and session.cookie_value not in page.text
        assert session.key not in str(page.headers)
    assert session.key not in refusal


def test_the_refusal_carries_the_same_headers_as_every_page(stranger: TestClient) -> None:
    refused = stranger.get("/")

    assert "default-src 'self'" in refused.headers["content-security-policy"]
    assert refused.headers["cache-control"] == "no-store"
    assert not re.search(r"<script(?![^>]*\bsrc=)", refused.text) and " style=" not in refused.text


def test_a_request_for_another_host_is_refused_before_the_key_is_looked_at(stranger: TestClient) -> None:
    entered = stranger.get(session_of(stranger).entry_path, headers={"host": "other.example"})

    assert entered.status_code == 400 and "set-cookie" not in entered.headers


def test_two_boards_on_one_machine_keep_their_cookies_apart() -> None:
    first, second = session_for(8484), session_for(8485)

    assert first.cookie_name != second.cookie_name and first.key != second.key
    assert entry_address(8484, first) == f"http://127.0.0.1:8484/enter?key={first.key}"
    assert not second.admits({first.cookie_name: first.cookie_value})


def test_the_security_text_says_another_server_on_the_address_gets_the_cookie() -> None:
    text = " ".join((Path(__file__).resolve().parents[1] / "SECURITY.md").read_text(encoding="utf-8").split())

    assert "another web server on `127.0.0.1` that you open in the same browser receives" in text
    assert "changes at each start" in text


def test_the_printed_address_lets_one_browser_in_and_no_second(stranger: TestClient) -> None:
    path = session_of(stranger).entry_path
    first = stranger.get(path)
    second_browser = TestClient(stranger.app, base_url=f"http://{HOST}", follow_redirects=False)

    refused = second_browser.get(path)

    assert first.status_code == 303
    assert refused.status_code == 401 and "set-cookie" not in refused.headers
    assert "works once" in refused.text and "loopcaptain serve" in refused.text
    assert second_browser.get("/").status_code == 401


def test_the_browser_let_in_may_open_the_address_again(stranger: TestClient) -> None:
    path = session_of(stranger).entry_path
    stranger.get(path)

    again = stranger.get(f"{path}&next=/connect")

    assert again.status_code == 303 and again.headers["location"] == "/connect"
