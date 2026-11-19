"""A loop id that two watched repositories share is named on the overview and on the loop page."""

from __future__ import annotations

import types
from pathlib import Path

from fastapi.testclient import TestClient

from loopcaptain.board.app import create_app
from loopcaptain.board.discover import Config
from loopcaptain.board.overview import repeated_ids
from loopcaptain.board.steer import Runner

HOST = "board.test"


def board(repos: tuple[Path, ...], state: Path) -> TestClient:
    app = create_app(
        config=lambda: Config(repos=repos), runner=Runner(state), allowed_hosts=frozenset({HOST})
    )
    client = TestClient(app, base_url=f"http://{HOST}")
    session = app.state.session
    client.cookies.set(session.cookie_name, session.issue() or "")
    return client


def two_repos(tmp_path: Path, helper: types.ModuleType, second_id: str) -> tuple[Path, Path]:
    first, second = tmp_path / "alpha-repo", tmp_path / "beta-repo"
    for repo in (first, second):
        repo.mkdir()
    helper.register("scan", {"title": "Scan in alpha"}, first)
    helper.register(second_id, {"title": "Scan in beta"}, second)
    helper.register("other", {"title": "Other"}, first)
    return first, second


def test_repeated_ids_names_each_id_two_repositories_use_once() -> None:
    pairs = [("a", "scan"), ("b", "scan"), ("a", "other"), ("a", "scan"), ("c", "plan")]

    assert repeated_ids(pairs) == {"scan": ("a", "b")}


def test_the_overview_warns_when_two_repositories_have_a_loop_with_one_id(
    tmp_path: Path, helper: types.ModuleType
) -> None:
    client = board(two_repos(tmp_path, helper, "scan"), tmp_path / "s")

    page = client.get("/").text

    assert "watched repositories have a loop with the same id" in page
    assert "<code>scan</code> in alpha-repo and beta-repo" in page


def test_the_loop_page_names_the_other_repository_with_the_same_id(
    tmp_path: Path, helper: types.ModuleType
) -> None:
    client = board(two_repos(tmp_path, helper, "scan"), tmp_path / "s")

    page = client.get("/loop/alpha-repo/scan").text
    other = client.get("/loop/alpha-repo/other").text

    assert 'href="http://board.test/loop/beta-repo/scan">beta-repo</a> also has a loop with this id.' in page
    assert "Check you are answering the right one." in page
    assert "helper" not in page.split("flash warn", 1)[1].split("</p>", 1)[0]
    assert "also has a loop with this id" not in other


def test_no_warning_where_every_id_is_its_own(tmp_path: Path, helper: types.ModuleType) -> None:
    client = board(two_repos(tmp_path, helper, "scan-two"), tmp_path / "s")

    assert "the same id" not in client.get("/").text
    assert "also has a loop with this id" not in client.get("/loop/alpha-repo/scan").text
