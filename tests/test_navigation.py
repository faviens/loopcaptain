"""Finding the way: the menu says where a page belongs, and every way back is a real target."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loopcaptain.board.app import create_app
from loopcaptain.board.discover import Config
from loopcaptain.board.steer import Runner

HOST = "board.test"


@pytest.fixture
def client(scan: Path, tmp_path: Path) -> TestClient:
    app = create_app(
        config=lambda: Config(repos=(scan,)),
        runner=Runner(tmp_path / "state"),
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
