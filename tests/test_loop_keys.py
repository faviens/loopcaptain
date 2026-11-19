"""A loop holds the key of its own inbox and of no other."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from loopcaptain.board.discover import Repo, load_loop
from loopcaptain.board.steer import minimal_env
from loopcaptain.protocol import signing, store


def line(kind: str, loop: str, at: datetime | None = None) -> dict[str, Any]:
    stamp = (at or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
    return {"id": f"forged-{kind}", "ts": stamp, "kind": kind, "loop": loop, "text": "Ship it."}


def marked(body: dict[str, Any], key: bytes, name: str, without: tuple[str, ...]) -> dict[str, Any]:
    kept = {field: value for field, value in body.items() if field not in without}
    text = json.dumps(kept, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {**body, name: hmac.new(key, text.encode(), hashlib.sha256).hexdigest()}


def append(folder: Path, body: dict[str, Any]) -> None:
    with (folder / "inbox.jsonl").open("a", encoding="utf-8") as inbox:
        inbox.write(json.dumps(body) + "\n")


def earlier_signed(entry: dict[str, Any], loop_id: str) -> bool | None:
    """`signed` as the standard printed it while one key signed for every loop."""
    key = Path(os.environ.get("LOOPCAPTAIN_INBOX_KEY") or "~/.config/loopcaptain/inbox.key").expanduser()
    if not key.is_file():
        return None
    if entry.get("loop") != loop_id:
        return False
    body = {key: value for key, value in entry.items() if key != "sig"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    secret = bytes.fromhex(key.read_text(encoding="utf-8").strip())
    mark = hmac.new(secret, text.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(mark, str(entry.get("sig", "")))


@pytest.fixture
def two(tmp_path: Path, helper: types.ModuleType) -> tuple[Path, Path]:
    """Two repositories, each with a loop of the same name, both seen by a board."""
    first, second = tmp_path / "first", tmp_path / "second"
    keys = signing.board_keys()
    for repo in (first, second):
        helper.register("scan", {"title": "Scan"}, repo)
        signing.hand_out(keys, repo / ".loops" / "scan")
    return first, second


def test_a_loop_cannot_sign_a_stop_for_the_same_loop_name_in_another_repository(
    two: tuple[Path, Path], helper: types.ModuleType
) -> None:
    first, second = two
    there = second / ".loops" / "scan"
    held = signing.read_loop_key(first / ".loops" / "scan")
    assert held is not None

    append(there, marked(line("stop", "scan"), held, "loop_sig", ("sig", "loop_sig")))
    view = load_loop(Repo("second", second), "scan")

    assert [entry["signed"] for entry in helper.inbox("scan", second)] == [False]
    assert view.state is not None and not view.state.stop_requested


def test_a_loop_reads_its_own_key_and_never_the_secret_all_keys_are_made_from(
    two: tuple[Path, Path], helper: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, _ = two
    sent = store.append_inbox(first, "scan", "stop", keys=signing.board_keys())
    opened: list[str] = []
    read_text = Path.read_text

    def watched(self: Path, *args: Any, **named: Any) -> str:
        opened.append(self.name)
        return read_text(self, *args, **named)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", watched)
        taken = helper.inbox("scan", first)

    own = signing.loop_key_file(first / ".loops" / "scan")
    assert [(entry["id"], entry["signed"]) for entry in taken] == [(sent.id, True)]
    assert own.name in opened and "board.key" not in opened and "inbox.key" not in opened
    assert oct(own.stat().st_mode & 0o777) == "0o600" and oct(own.parent.stat().st_mode & 0o777) == "0o700"
    assert oct(signing.secret_path().stat().st_mode & 0o777) == "0o600"


def test_the_one_key_of_earlier_versions_signs_nothing_the_board_or_a_loop_takes(
    two: tuple[Path, Path], helper: types.ModuleType
) -> None:
    first, _ = two
    folder = first / ".loops" / "scan"
    machine = signing.read_key()
    assert machine is not None

    append(folder, marked(line("stop", "scan"), machine, "sig", ("sig",)))
    view = load_loop(Repo("first", first), "scan")

    assert [entry["signed"] for entry in helper.inbox("scan", first)] == [False]
    assert view.state is not None and not view.state.stop_requested


def test_a_line_from_before_the_boards_secret_still_reads_as_the_boards_own(
    two: tuple[Path, Path],
) -> None:
    first, _ = two
    folder = first / ".loops" / "scan"
    keys = signing.read_board_keys()
    assert keys is not None and keys.machine is not None
    before = datetime.fromtimestamp(keys.since, UTC) - timedelta(days=3)
    old = marked(line("stop", "scan", before), keys.machine, "sig", ("sig",))
    elsewhere = marked(line("stop", "other", before), keys.machine, "sig", ("sig",))

    assert signing.is_from_board(old, keys, folder, "scan") is True
    assert signing.is_from_board(elsewhere, keys, folder, "scan") is False
    assert signing.is_from_board({**old, "text": "Changed."}, keys, folder, "scan") is False


def test_a_helper_pasted_from_the_earlier_text_still_takes_the_boards_lines(
    two: tuple[Path, Path],
) -> None:
    first, _ = two
    sent = store.append_inbox(first, "scan", "stop", keys=signing.board_keys())
    written = json.loads((first / ".loops" / "scan" / "inbox.jsonl").read_text().splitlines()[-1])

    assert sent.loop_sig and sent.sig and sent.loop_sig != sent.sig
    assert earlier_signed(written, "scan") is True
    assert earlier_signed({**written, "text": "Changed."}, "scan") is False


def test_a_started_loop_is_told_where_the_keys_are_and_handed_no_key(two: tuple[Path, Path]) -> None:
    env = minimal_env()
    secret = signing.secret_path().read_text().strip()

    assert env["LOOPCAPTAIN_INBOX_KEY"] == str(signing.key_path())
    assert secret not in "".join(env.values())


def test_a_moved_loop_folder_has_another_key(two: tuple[Path, Path]) -> None:
    first, second = two
    keys = signing.board_keys()
    here, there = first / ".loops" / "scan", second / ".loops" / "scan"

    assert signing.loop_key(keys.secret, here) != signing.loop_key(keys.secret, there)
    assert signing.loop_key_file(here) != signing.loop_key_file(there)
    assert signing.loop_key(keys.secret, here) == signing.loop_key(
        keys.secret, first / ".loops" / "." / "scan"
    )
