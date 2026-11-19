"""Guards of the protocol layer, one assertion each: removing one must fail a test."""

from __future__ import annotations

import shutil
import types
from pathlib import Path

import pytest

from loopcaptain.protocol import signing, store
from loopcaptain.protocol.signing import board_keys, hand_out, is_signed, loop_key, untrusted_ids
from loopcaptain.protocol.store import StoreError


def two_loops(repo: Path, helper: types.ModuleType) -> None:
    helper.register("scan", {"title": "Scan"}, repo)
    helper.register("other", {"title": "Other"}, repo)


def test_a_signed_line_copied_into_another_loops_inbox_is_not_signed_there(
    repo: Path, helper: types.ModuleType
) -> None:
    two_loops(repo, helper)
    keys = board_keys()
    here, there = repo / ".loops" / "scan", repo / ".loops" / "other"
    sent = store.append_inbox(repo, "scan", "stop", keys=keys)
    shutil.copy(here / "inbox.jsonl", there / "inbox.jsonl")
    hand_out(keys, there)

    copied, _ = store.read_inbox(repo, "other")
    taken_there = helper.inbox("other", repo)
    key = loop_key(keys.secret, here)

    assert is_signed(sent.body(), key, "scan") is True and is_signed(sent.body(), key) is True
    assert is_signed(copied[0].body(), key, "other") is False
    assert is_signed(copied[0].body(), loop_key(keys.secret, there), "other") is False
    assert untrusted_ids(copied, "other", there) == frozenset({sent.id})
    assert untrusted_ids(store.read_inbox(repo, "scan")[0], "scan", here) == frozenset()
    assert [entry["signed"] for entry in taken_there] == [False]


def test_the_key_is_where_the_environment_says_and_else_in_the_config_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    named = signing.key_path()
    monkeypatch.setenv(signing.KEY_ENV, "~/elsewhere/inbox.key")
    in_home = signing.key_path()
    monkeypatch.setenv(signing.KEY_ENV, "")
    empty = signing.key_path()
    monkeypatch.delenv(signing.KEY_ENV)
    unset = signing.key_path()

    assert named == tmp_path / "inbox.key"
    assert in_home == Path.home() / "elsewhere" / "inbox.key"
    assert empty == unset == Path.home() / ".config" / "loopcaptain" / "inbox.key"


def test_a_loop_folder_that_is_a_link_or_has_no_id_for_a_name_is_not_a_loop(
    repo: Path, helper: types.ModuleType
) -> None:
    two_loops(repo, helper)
    folder = repo / ".loops"
    (folder / "linked").symlink_to(folder / "scan", target_is_directory=True)
    shutil.copytree(folder / "scan", folder / "Not An Id")

    assert store.loop_ids(repo) == ["other", "scan"]


def test_a_loop_json_that_names_another_loop_than_its_folder_is_refused(
    repo: Path, helper: types.ModuleType
) -> None:
    two_loops(repo, helper)
    shutil.copy(repo / ".loops" / "scan" / "loop.json", repo / ".loops" / "other" / "loop.json")

    with pytest.raises(StoreError, match="id 'scan' does not match its folder 'other'"):
        store.read_manifest(repo, "other")
    assert store.read_manifest(repo, "scan").id == "scan"


def test_a_signed_stop_appended_a_second_time_is_taken_once(repo: Path, helper: types.ModuleType) -> None:
    """A copy of a signed line is signed too; what holds it back is the id the loop has read."""
    helper.register("scan", {"title": "Scan"}, repo)
    store.append_inbox(repo, "scan", "stop", keys=board_keys())
    inbox = repo / ".loops" / "scan" / "inbox.jsonl"
    signed_line = inbox.read_text(encoding="utf-8")

    first = helper.inbox("scan", repo)
    with inbox.open("a", encoding="utf-8") as handle:
        handle.write(signed_line)

    assert [entry["signed"] for entry in first] == [True]
    assert helper.inbox("scan", repo) == [] and store.take_inbox(repo, "scan") == []
