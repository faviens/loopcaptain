"""Finding the way: the menu says where a page belongs, and every way back is a real target."""

from __future__ import annotations

import json
import os
import re
import types
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from loopcaptain.board import steer
from loopcaptain.board.app import create_app
from loopcaptain.board.discover import Config, find_repos
from loopcaptain.board.steer import Runner

HOST = "board.test"


@pytest.fixture
def runner(tmp_path: Path) -> Runner:
    return Runner(tmp_path / "state")


@pytest.fixture
def client(scan: Path, runner: Runner) -> TestClient:
    app = create_app(
        config=lambda: Config(repos=(scan,)),
        runner=runner,
        allowed_hosts=frozenset({HOST}),
    )
    session = app.state.session
    browser = TestClient(app, base_url=f"http://{HOST}", follow_redirects=False)
    browser.cookies.set(session.cookie_name, session.cookie_value)
    return browser


def menu_link(page: str, label: str) -> str:
    """The `<a>` of the top menu that reads `label`."""
    menu = page.split('<nav class="strip"', 1)[1].split("</nav>", 1)[0]
    found = re.search(rf"<a [^>]*>{label}</a>", menu)
    assert found, label
    return found.group(0)


@pytest.mark.parametrize(
    "path",
    ["/loop/some-repo/scan", "/loop/some-repo/scan?tab=rounds", "/loop/some-repo/scan/file?path=brief.md"],
)
def test_the_menu_marks_loops_on_a_loop_and_a_file_page(client: TestClient, scan: Path, path: str) -> None:
    (scan / "brief.md").write_text("# Brief\n", encoding="utf-8")

    page = client.get(path).text

    assert 'aria-current="true"' in menu_link(page, "Loops")
    assert "aria-current" not in menu_link(page, "Connect a loop")


def test_the_menu_marks_loops_as_the_page_itself_only_on_the_overview(client: TestClient) -> None:
    assert 'aria-current="page"' in menu_link(client.get("/").text, "Loops")
    assert "aria-current" not in menu_link(client.get("/connect").text, "Loops")


STYLE = Path(__file__).resolve().parents[1] / "src" / "loopcaptain" / "board" / "static" / "style.css"


def rules_for(selector: str) -> str:
    """Every declaration the style sheet gives `selector` on its own or in a list of selectors."""
    sheet = re.sub(r"/\*.*?\*/", "", STYLE.read_text(encoding="utf-8"), flags=re.S)
    found = re.findall(r"([^{}]+)\{([^}]*)\}", sheet)
    return " ".join(body for head, body in found if selector in [part.strip() for part in head.split(",")])


def test_the_way_back_above_a_heading_is_a_target_as_tall_as_any_control() -> None:
    crumb = rules_for(".crumb a")

    assert "min-height: 44px" in crumb
    assert "text-decoration: none" not in crumb, "a link that does not look like one"
    assert "var(--accent)" in crumb, "links are the one action colour"


@pytest.mark.parametrize("tab", ["overview", "findings"])
def test_every_form_on_a_loop_page_carries_the_tab_it_was_drawn_on(
    client: TestClient, scan: Path, helper: types.ModuleType, tab: str
) -> None:
    helper.emit("scan", "question", {"round": 2, "text": "Per seat or per site?"}, scan)

    page = client.get(f"/loop/some-repo/scan?tab={tab}").text

    forms = re.findall(r'<form [^>]*method="post".*?</form>', page, re.S)
    assert forms
    for form in forms:
        assert f'<input type="hidden" name="tab" value="{tab}">' in form, form[:80]


@pytest.mark.parametrize(
    ("given", "lands"),
    [("rounds", "/loop/some-repo/scan?tab=rounds&note=Sent"), ("overview", "/loop/some-repo/scan?note=Sent")],
)
def test_an_answer_leads_back_to_the_tab_it_was_sent_from(client: TestClient, given: str, lands: str) -> None:
    form = {"token": str(client.app.state.token), "text": "Per seat.", "tab": given}  # type: ignore[attr-defined]

    sent = client.post("/loop/some-repo/scan/reply", data=form)

    assert sent.headers["location"].startswith(lands)


def test_a_tab_the_page_does_not_have_leads_to_the_bare_page(client: TestClient) -> None:
    form = {"token": str(client.app.state.token), "tab": "x\r\nSet-Cookie: a=b"}  # type: ignore[attr-defined]

    sent = client.post("/loop/some-repo/scan/stop", data=form)

    assert sent.headers["location"].startswith("/loop/some-repo/scan?note=Stop")


def tile(page: str, words: str) -> str:
    """The key figure on the overview whose caption reads `words`, from its opening tag."""
    found = re.search(rf'<(a|div) [^>]*class="kpi[^"]*"[^>]*><b>[^<]*</b><span>{words}</span>', page)
    assert found, words
    return found.group(0)


def test_the_figures_that_ask_for_a_look_lead_to_what_they_count(client: TestClient) -> None:
    page = client.get("/").text

    assert '/?tab=waiting"' in tile(page, "wait[s]? for your answer")
    assert '/?status=running"' in tile(page, "running now")
    assert '/?status=stalled&amp;status=failed"' in tile(page, "stalled or failed")


def test_the_status_filter_takes_more_than_one_status(client: TestClient, scan: Path) -> None:
    both = client.get("/?status=running&status=stalled").text
    other = client.get("/?status=stalled&status=failed").text

    assert "Market scan" in both, "the loop runs, which is one of the two"
    assert "Market scan" not in other.split('<table class="loops">')[-1]


def test_end_says_so_when_the_remembered_process_had_already_ended(
    client: TestClient, scan: Path, runner: Runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    def gone(pid: int, sig: int) -> None:
        raise ProcessLookupError(3, "No such process")

    repo = find_repos(Config(repos=(scan,)))[0]
    record = {"pid": 4242, "command": "x", "started": "2026-11-14T21:00:00+00:00", "boot": steer.boot_time()}
    steer.write_private(runner.record_path(repo, "scan"), json.dumps(record | {"repo": steer.identity(repo)}))
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)  # the pid answers, as a reused one would
    monkeypatch.setattr(os, "killpg", gone)  # but leads no process group

    ended = client.post("/loop/some-repo/scan/kill", data={"token": str(client.app.state.token)})  # type: ignore[attr-defined]

    location = unquote(ended.headers["location"])
    assert "had already ended" in location and "told to end" not in location


SCRIPT = STYLE.parent / "board.js"


def test_the_script_keeps_tabs_and_answers_out_of_the_history() -> None:
    """Back from a loop page leads to the list in one press: a tab or an answer replaces the entry.

    The browser's history itself is checked by hand; this holds the script to the way it does it."""
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'querySelectorAll("nav.tabs a, th.rnd a")' in script
    assert 'form[method="post"]' in script and "fetch(form.action" in script
    assert "window.location.replace(response.url)" in script
    assert "form.submit()" in script, "without a usable answer the form is sent the old way"
    assert "carried.name = button.name" in script, "the old way keeps the button that was pressed"


def test_a_form_still_works_without_the_script(client: TestClient) -> None:
    form = {"token": str(client.app.state.token), "text": "A note."}  # type: ignore[attr-defined]

    sent = client.post("/loop/some-repo/scan/reply", data=form)

    assert sent.status_code == 303 and sent.headers["location"].startswith("/loop/some-repo/scan?note=Sent")
