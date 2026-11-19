"""A refusal or a fault is a page of the board with the reason and a way back, and a message shows once."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loopcaptain.board.app import create_app
from loopcaptain.board.discover import Config
from loopcaptain.board.errors import CONTENT_POLICY
from loopcaptain.board.steer import Runner
from loopcaptain.protocol import store

HOST = "board.test"
PAGE = {"accept": "text/html,application/xhtml+xml"}
STATIC = Path(__file__).resolve().parents[1] / "src" / "loopcaptain" / "board" / "static"


@pytest.fixture
def client(scan: Path, tmp_path: Path) -> TestClient:
    app = create_app(
        config=lambda: Config(repos=(scan,)),
        runner=Runner(tmp_path / "state"),
        allowed_hosts=frozenset({HOST}),
    )
    client = TestClient(app, base_url=f"http://{HOST}", follow_redirects=False, raise_server_exceptions=False)
    client.cookies.set(app.state.session.cookie_name, app.state.session.issue() or "")
    return client


@pytest.mark.parametrize(
    ("path", "words"),
    [
        ("/loop/some-repo/ghost", "no such loop on this board"),
        ("/loop/other-repo/scan", "no such loop on this board"),
        ("/loop/some-repo/scan/file?path=missing.md", "this loop names no such file"),
        ("/nothing/here", "Not Found"),
    ],
)
def test_what_is_not_there_is_a_page_with_the_reason_and_a_way_back(
    client: TestClient, path: str, words: str
) -> None:
    page = client.get(path, headers=PAGE)

    assert page.status_code == 404 and page.headers["content-type"].startswith("text/html")
    assert "<h1>Not on this board</h1>" in page.text and words in page.text
    assert 'href="http://board.test/"' in page.text or 'href="/"' in page.text
    assert "default-src 'self'" in page.headers["content-security-policy"]


def test_a_missing_file_leads_back_to_its_loop(client: TestClient) -> None:
    page = client.get("/loop/some-repo/scan/file?path=missing.md", headers=PAGE).text
    unknown = client.get("/loop/some-repo/ghost", headers=PAGE).text

    assert "/loop/some-repo/scan" in page and "Back to the loop" in page
    assert "Back to the loop" not in unknown


def test_a_script_that_fetches_gets_the_reason_as_json(client: TestClient) -> None:
    answer = client.get("/loop/some-repo/ghost/pulse")

    assert answer.status_code == 404 and answer.json() == {"detail": "no such loop on this board"}


@pytest.mark.parametrize("action", ["reply", "stop", "start", "kill"])
def test_a_form_from_before_a_restart_leads_to_the_loops_page_which_says_so(
    client: TestClient, scan: Path, action: str
) -> None:
    sent = client.post(
        f"/loop/some-repo/scan/{action}", data={"token": "from-an-earlier-start", "text": "x"}, headers=PAGE
    )
    page = client.get(sent.headers["location"], headers=PAGE)

    assert sent.status_code == 303
    assert page.status_code == 200 and 'class="flash bad"' in page.text
    assert "drawn before the board last started" in page.text and "Market scan" in page.text
    assert store.read_inbox(scan, "scan") == ([], [])


def test_a_form_without_its_token_is_a_page_that_says_what_to_do(client: TestClient, scan: Path) -> None:
    page = client.post("/loop/some-repo/scan/stop", data={}, headers=PAGE)

    assert page.status_code == 422 and "<h1>Nothing was sent: the form was incomplete</h1>" in page.text
    assert "token" in page.text and "reload the page" in page.text and "Back to the loop" in page.text
    assert store.read_inbox(scan, "scan") == ([], [])


def test_a_fault_is_a_page_too_and_the_next_request_works(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(repo: Path, loop_id: str) -> str:
        raise RuntimeError("the disk said no")

    monkeypatch.setattr(store, "fingerprint", broken)
    page = client.get("/loop/some-repo/scan", headers=PAGE)
    fetched = client.get("/loop/some-repo/scan/pulse")
    monkeypatch.undo()

    assert page.status_code == 500 and "<h1>The board ran into a fault</h1>" in page.text
    for answer in (page, fetched):
        assert answer.headers["content-security-policy"] == CONTENT_POLICY
        assert answer.headers["x-content-type-options"] == "nosniff"
        assert (
            answer.headers["referrer-policy"] == "no-referrer"
            and answer.headers["cache-control"] == "no-store"
        )
    assert "the disk said no" in page.text and "Traceback" not in page.text
    assert fetched.status_code == 500 and "the disk said no" in fetched.json()["detail"]
    assert client.get("/loop/some-repo/scan", headers=PAGE).status_code == 200


def test_an_error_page_carries_no_inline_script_or_style(client: TestClient) -> None:
    page = client.get("/loop/some-repo/ghost", headers=PAGE).text

    assert "<script>" not in page and " style=" not in page and " onclick=" not in page


def test_the_script_takes_a_shown_message_out_of_the_address() -> None:
    script = (STATIC / "board.js").read_text(encoding="utf-8")

    assert '["note", "error", "seal"]' in script and "history.replaceState" in script
    assert "searchParams.delete(name)" in script


def test_the_script_still_holds_a_reload_while_an_answer_is_being_typed() -> None:
    script = (STATIC / "board.js").read_text(encoding="utf-8")

    assert 'querySelectorAll("textarea[name]")' in script and "field === document.activeElement" in script
    assert "!busy()) window.location.reload()" in script
