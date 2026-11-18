"""Which file names the viewer refuses: a block-list of the names tools keep keys and passwords under."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from loopcaptain.board import app as board_app
from loopcaptain.board.app import create_app
from loopcaptain.board.discover import Config
from loopcaptain.board.files import PRIVATE_PARTS, PRIVATE_PATTERNS, inside, is_private, read_bounded
from loopcaptain.board.steer import Runner

#: One name per pattern, in the order of `PRIVATE_PATTERNS`: the test below holds the two together.
NAME_FOR_PATTERN = {
    ".env*": ".envrc",
    "*.env": "prod.env",
    "*.env.*": "app.env.production",
    "*.pem": "server.pem",
    "*.pem.*": "server.pem.bak",
    "*.key": "deploy.key",
    "*.key.*": "deploy.key.old",
    "*.ppk": "box.ppk",
    "*.p12": "client.p12",
    "*.pfx": "client.pfx",
    "*.keystore": "release.keystore",
    "*.jks": "trust.jks",
    "*.keytab": "svc.keytab",
    "*.kdbx": "passwords.kdbx",
    "*.kdb": "passwords.kdb",
    "*.gpg": "vault.gpg",
    "*.pgp": "vault.pgp",
    "*.ovpn": "office.ovpn",
    "id_rsa*": "id_rsa.pub",
    "id_dsa*": "id_dsa",
    "id_ecdsa*": "id_ecdsa",
    "id_ed25519*": "id_ed25519",
    "id_xmss*": "id_xmss",
    "*_rsa": "deploy_rsa",
    "*_dsa": "deploy_dsa",
    "*_ecdsa": "deploy_ecdsa",
    "*_ed25519": "deploy_ed25519",
    "*.tfstate": "terraform.tfstate",
    "*.tfstate.*": "terraform.tfstate.backup",
    "*.tfvars": "prod.tfvars",
    "*.tfvars.json": "prod.tfvars.json",
    "credentials*": "credentials.yaml",
    "*credentials.*": "application_default_credentials.json",
    "*-credentials*": "db-credentials.txt",
    "*_credentials*": "db_credentials.txt",
    "secrets*": "secrets.yaml",
    "secret.*": "secret.txt",
    "*.secret": "api.secret",
    "*.secrets": "api.secrets",
    "*-secret.*": "client-secret.json",
    "*_secret.*": "api_secret.txt",
    "*-secrets.*": "prod-secrets.yaml",
    "*_secrets.*": "prod_secrets.yaml",
    "client_secret*": "client_secret_123.json",
    "service-account*.json": "service-account-prod.json",
    "service_account*.json": "service_account.json",
    "serviceaccount*.json": "serviceaccount.json",
    "*-sa-key*.json": "prod-sa-key-1.json",
    "*_sa_key*.json": "prod_sa_key.json",
}


def test_every_pattern_has_a_name_that_only_it_needs_to_refuse() -> None:
    assert tuple(NAME_FOR_PATTERN) == PRIVATE_PATTERNS


@pytest.mark.parametrize(("pattern", "name"), NAME_FOR_PATTERN.items())
def test_a_name_of_each_pattern_is_refused(tmp_path: Path, pattern: str, name: str) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / name).write_text("x")

    assert fnmatch.fnmatchcase(name, pattern) and is_private(name) and is_private(name.upper())
    with pytest.raises(HTTPException) as refused:
        inside(tmp_path, f"sub/{name}")
    assert refused.value.status_code == 404


@pytest.mark.parametrize("part", sorted(PRIVATE_PARTS))
def test_a_file_or_folder_of_each_private_name_is_refused(tmp_path: Path, part: str) -> None:
    (tmp_path / part).mkdir()
    (tmp_path / part / "notes.md").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / part).write_text("x")

    for path in (f"{part}/notes.md", f"sub/{part}"):
        with pytest.raises(HTTPException):
            inside(tmp_path, path)


@pytest.mark.parametrize(
    "name",
    [
        "plan.md",
        "review-round-3.md",
        "keys.md",
        "environment.md",
        "tokens.csv",
        "identity.md",
        "secretary.md",
        "credit.txt",
        "loop.json",
        "events.jsonl",
        "config.yaml",
    ],
)
def test_an_ordinary_name_is_still_shown(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_text("x")

    assert inside(tmp_path, name) == (tmp_path / name).resolve()


def test_a_file_is_read_whole_up_to_the_limit_and_only_measured_above_it(tmp_path: Path) -> None:
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "plan.md").write_text("twelve bytes")
    target = inside(tmp_path, "notes/plan.md")

    assert read_bounded(tmp_path, target) == (12, b"twelve bytes")
    assert read_bounded(tmp_path, target, limit=5) == (12, None)


def test_a_folder_swapped_for_a_link_after_the_check_is_not_followed(tmp_path: Path) -> None:
    repo, outside = tmp_path / "repo", tmp_path / "outside"
    (repo / "notes").mkdir(parents=True)
    (repo / "notes" / "plan.md").write_text("the plan")
    outside.mkdir()
    (outside / "plan.md").write_text("not the loop's to show")
    target = inside(repo, "notes/plan.md")

    (repo / "notes" / "plan.md").unlink()
    (repo / "notes").rmdir()
    (repo / "notes").symlink_to(outside)

    with pytest.raises(OSError):
        read_bounded(repo, target)


def test_a_file_swapped_for_a_link_or_a_pipe_after_the_check_is_not_read(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "outside.md").write_text("not the loop's to show")
    for name in ("plan.md", "feed.md"):
        (repo / name).write_text("the plan")
    plan, feed = inside(repo, "plan.md"), inside(repo, "feed.md")

    plan.unlink()
    plan.symlink_to(tmp_path / "outside.md")
    feed.unlink()
    os.mkfifo(feed)

    for target in (plan, feed):
        with pytest.raises(OSError):
            read_bounded(repo, target)


def test_the_page_answers_no_such_file_when_the_file_became_a_link_after_the_check(
    scan: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "outside.md").write_text("not the loop's to show")
    (scan / "plan.md").write_text("the plan")
    app = create_app(
        config=lambda: Config(repos=(scan,)),
        runner=Runner(tmp_path / "state"),
        allowed_hosts=frozenset({"board.test"}),
    )
    client = TestClient(app, base_url="http://board.test", follow_redirects=False)
    client.cookies.set(app.state.session.cookie_name, app.state.session.issue() or "")
    shown = client.get("/loop/some-repo/scan/file", params={"path": "plan.md"})

    def checked_then_swapped(repo: Path, relative: str) -> Path:
        target = inside(repo, relative)
        target.unlink()
        target.symlink_to(tmp_path / "outside.md")
        return target

    monkeypatch.setattr(board_app, "inside", checked_then_swapped)
    swapped = client.get("/loop/some-repo/scan/file", params={"path": "plan.md"})

    assert shown.status_code == 200 and "the plan" in shown.text
    assert swapped.status_code == 404 and "not the loop" not in swapped.text
