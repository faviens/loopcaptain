"""The branch on a loop page is read from the checkout's files: the board runs no `git`."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loopcaptain.board.app import create_app
from loopcaptain.board.discover import Config, git_branch, git_common_dir
from loopcaptain.board.steer import Runner

HOST = "board.test"


def checkout(path: Path, head: str) -> None:
    (path / ".git").mkdir()
    (path / ".git" / "HEAD").write_text(head)


def worktree(main: Path, path: Path, head: str, *, listed_back: bool = True) -> None:
    """A worktree as git lays it out: a `.git` file naming a folder that names the file back."""
    git_dir = main / ".git" / "worktrees" / path.name
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text(head)
    (git_dir / "gitdir").write_text(f"{path / '.git' if listed_back else main / 'elsewhere' / '.git'}\n")
    path.mkdir()
    (path / ".git").write_text(f"gitdir: {git_dir}\n")


def test_the_branch_is_the_one_the_head_file_names(tmp_path: Path) -> None:
    checkout(tmp_path, "ref: refs/heads/loop/scan\n")

    assert git_branch(tmp_path) == "loop/scan"


@pytest.mark.parametrize("head", ["3f1c9d2a7b\n", "", "ref: refs/tags/v1\n", "\xff\xfe"])
def test_a_head_that_names_no_branch_gives_none(tmp_path: Path, head: str) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_bytes(head.encode("latin-1"))

    assert git_branch(tmp_path) == ""


def test_a_pipe_in_the_place_of_gits_files_holds_no_page(tmp_path: Path) -> None:
    piped_head, piped_git = tmp_path / "a", tmp_path / "b"
    (piped_head / ".git").mkdir(parents=True)
    os.mkfifo(piped_head / ".git" / "HEAD")
    piped_git.mkdir()
    os.mkfifo(piped_git / ".git")

    assert git_branch(piped_head) == "" and git_branch(piped_git) == ""
    assert git_common_dir(piped_git) == piped_git.resolve()


def test_a_git_folder_linked_to_that_of_another_repository_is_not_taken_for_it(tmp_path: Path) -> None:
    other, claims = tmp_path / "other", tmp_path / "claims"
    other.mkdir()
    checkout(other, "ref: refs/heads/their-branch\n")
    claims.mkdir()
    (claims / ".git").symlink_to(other / ".git")

    assert git_branch(claims) == ""
    assert git_common_dir(claims) == claims.resolve() != git_common_dir(other)


@pytest.mark.parametrize("name", ["x" * 201, "main\u202egpj.exe", "main\u3164"])
def test_a_branch_name_that_is_too_long_or_does_not_show_is_not_shown(tmp_path: Path, name: str) -> None:
    checkout(tmp_path, f"ref: refs/heads/{name}\n")

    assert git_branch(tmp_path) == ""


def test_a_folder_without_git_has_no_branch(tmp_path: Path) -> None:
    assert git_branch(tmp_path) == ""


def test_a_worktree_shows_its_own_branch_only_when_its_repository_lists_it_back(tmp_path: Path) -> None:
    main = tmp_path / "main"
    main.mkdir()
    checkout(main, "ref: refs/heads/main\n")
    worktree(main, tmp_path / "side", "ref: refs/heads/side\n")
    worktree(main, tmp_path / "claims", "ref: refs/heads/secret-name\n", listed_back=False)

    assert git_branch(tmp_path / "side") == "side"
    assert git_branch(tmp_path / "claims") == ""


def test_a_loop_page_shows_the_branch_and_runs_no_program(
    scan: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout(scan, "ref: refs/heads/loop/scan\n")
    app = create_app(
        config=lambda: Config(repos=(scan,)),
        runner=Runner(tmp_path / "state"),
        allowed_hosts=frozenset({HOST}),
    )
    client = TestClient(app, base_url=f"http://{HOST}", follow_redirects=False)
    client.cookies.set(app.state.session.cookie_name, app.state.session.issue() or "")

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"the board ran a program to draw a page: {args}")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)

    pages = [client.get("/"), client.get("/loop/some-repo/scan"), client.get("/loop/some-repo/scan/pulse")]

    assert [page.status_code for page in pages] == [200, 200, 200]
    assert "branch <code>loop/scan</code>" in pages[1].text
