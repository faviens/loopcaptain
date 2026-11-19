"""The board's mark on the inbox: an HMAC over each line it writes, with a key of that loop alone.

The inbox is a plain file in the loop's repository, so an agent that can write files there could
add a `reply` that reads as the person or a `stop` that ends the run. The board signs every line,
`loop_sig`, with a key made for that one loop folder from a secret only the board reads
(`board.key`), and puts that loop's key in a file of its own (`keys/<name>.key`) for the loop to
check with. A loop that holds its key can sign for its own inbox and for no other. All of it is in
the user's config folder, outside every watched repository. This protects against agents confined
to their repository and to their own key, not against a process with the user's full file access,
which can read the board's secret too.

`sig`, under the one key of earlier versions (`inbox.key`), is still put on every line: a helper
pasted from an earlier text checks nothing else. The board itself does not trust it, except on a
line from before its secret existed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from loopcaptain.protocol.models import InboxEntry

log = logging.getLogger("loopcaptain.signing")

KEY_ENV = "LOOPCAPTAIN_INBOX_KEY"
DEFAULT_KEY = Path("~/.config/loopcaptain/inbox.key")
SECRET_FILE = "board.key"
KEYS_FOLDER = "keys"
LOOP_KEY_LABEL = b"loopcaptain loop key 1\0"
NAME_LENGTH = 32
KEY_BYTES = 32
PRIVATE_MODE = 0o600
PRIVATE_DIR_MODE = 0o700
MARKS = ("sig", "loop_sig")


@dataclass(frozen=True)
class BoardKeys:
    """What the board signs with. `secret` never leaves the board: every loop's key is made from it.
    `machine` is the one key of earlier versions, None where it cannot be read. `since` is when the
    secret was made: a line older than that can carry only `sig`."""

    secret: bytes
    machine: bytes | None
    since: float


def key_path() -> Path:
    """The file of the one key earlier versions signed with; its folder holds the rest."""
    return Path(os.environ.get(KEY_ENV) or DEFAULT_KEY).expanduser()


def secret_path() -> Path:
    return key_path().with_name(SECRET_FILE)


def read_hex(path: Path) -> bytes | None:
    """The key in a file, or None where there is none yet or it cannot be read."""
    try:
        key = bytes.fromhex(path.read_text(encoding="utf-8").strip())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        log.warning("the key at %s cannot be read: %s", path, error)
        return None
    if len(key) < KEY_BYTES:
        log.warning("the key at %s is too short; it is not used", path)
        return None
    return key


def read_key() -> bytes | None:
    """The one key of earlier versions, or None."""
    return read_hex(key_path())


def made_key(path: Path) -> bytes:
    """The key in a file, created readable by this user only on first use."""
    found = read_hex(path)
    if found:
        return found
    path.parent.mkdir(mode=PRIVATE_DIR_MODE, parents=True, exist_ok=True)
    key = secrets.token_bytes(KEY_BYTES)
    # Written whole beside it, then linked into place: a reader never sees half a key, and of two
    # boards starting at once the second finds the first one's key instead of writing its own.
    draft = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
    descriptor = os.open(draft, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_MODE)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(key.hex() + "\n")
    try:
        os.link(draft, path)
    except FileExistsError:
        existing = read_hex(path)
        if existing is None:
            raise
        return existing
    finally:
        draft.unlink(missing_ok=True)
    log.info("created the key at %s", path)
    return key


def board_key() -> bytes:
    """The one key of earlier versions, created on first use."""
    return made_key(key_path())


def board_keys() -> BoardKeys:
    """The board's secret and the earlier key, each created on first use."""
    secret = made_key(secret_path())
    return BoardKeys(secret, board_key(), secret_path().stat().st_mtime)


def read_board_keys() -> BoardKeys | None:
    """What the board signs with, or None where no board has made its secret on this machine."""
    secret = read_hex(secret_path())
    if secret is None:
        return None
    return BoardKeys(secret, read_key(), secret_path().stat().st_mtime)


def loop_key(secret: bytes, folder: Path) -> bytes:
    """The key of one loop folder: of this folder at this place, so a loop of the same name in
    another repository has another."""
    return hmac.new(secret, LOOP_KEY_LABEL + str(folder.resolve()).encode("utf-8"), hashlib.sha256).digest()


def loop_key_file(folder: Path) -> Path:
    """Where a loop finds its key: named after its folder's place, which the loop knows too."""
    name = hashlib.sha256(str(folder.resolve()).encode("utf-8")).hexdigest()[:NAME_LENGTH]
    return key_path().parent / KEYS_FOLDER / f"{name}.key"


def read_loop_key(folder: Path) -> bytes | None:
    """A loop's key as the loop reads it, or None where the board has not put it there."""
    return read_hex(loop_key_file(folder))


def hand_out(keys: BoardKeys, folder: Path) -> Path:
    """Put a loop's key where the loop looks for it, readable by this user only."""
    path, key = loop_key_file(folder), loop_key(keys.secret, folder)
    if read_hex(path) == key:
        return path
    path.parent.mkdir(mode=PRIVATE_DIR_MODE, parents=True, exist_ok=True)
    draft = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
    descriptor = os.open(draft, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_MODE)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(key.hex() + "\n")
    os.replace(draft, path)
    return path


def canonical(entry: dict[str, Any], without: tuple[str, ...] = ("sig",)) -> bytes:
    """The bytes that are signed: the line without its marks, keys sorted, no spaces."""
    body = {key: value for key, value in entry.items() if key not in without}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign(entry: dict[str, Any], key: bytes, without: tuple[str, ...] = ("sig",)) -> str:
    return hmac.new(key, canonical(entry, without), hashlib.sha256).hexdigest()


def marks(entry: dict[str, Any], keys: BoardKeys, folder: Path) -> dict[str, str]:
    """The marks the board puts on a line: `loop_sig` under the loop's key, over the line without
    marks, and `sig` under the earlier key, over the line with `loop_sig`, as an earlier helper
    computes it."""
    found = {"loop_sig": sign(entry, loop_key(keys.secret, folder), MARKS)}
    if keys.machine is not None:
        found["sig"] = sign({**entry, **found}, keys.machine)
    return found


def is_signed(entry: dict[str, Any], key: bytes | None, loop_id: str | None = None) -> bool | None:
    """True if the board wrote this line for the loop whose key this is, False if not, None where
    there is no key.

    The line names its loop, so a signed line copied into another loop's inbox is not signed there.
    """
    if key is None:
        return None
    given = entry.get("loop_sig")
    if loop_id is not None and entry.get("loop") != loop_id:
        return False
    return isinstance(given, str) and hmac.compare_digest(given, sign(entry, key, MARKS))


def is_older(entry: dict[str, Any], moment: float) -> bool:
    try:
        return datetime.fromisoformat(str(entry.get("ts"))).timestamp() < moment
    except ValueError:
        return False


def is_from_board(entry: dict[str, Any], keys: BoardKeys | None, folder: Path, loop_id: str) -> bool | None:
    """The board's own reading of a line: its `loop_sig`, and for a line written before the board's
    secret existed the `sig` of that time. None where this machine has no board secret."""
    if keys is None:
        return None
    if "loop_sig" in entry or keys.machine is None or not is_older(entry, keys.since):
        return bool(is_signed(entry, loop_key(keys.secret, folder), loop_id))
    given = entry.get("sig")
    named = entry.get("loop") == loop_id
    return named and isinstance(given, str) and hmac.compare_digest(given, sign(entry, keys.machine))


def untrusted_ids(inbox: list[InboxEntry], loop_id: str, folder: Path) -> frozenset[str]:
    """The inbox entries the board did not write. Without a secret here nothing can be told apart."""
    keys = read_board_keys()
    return frozenset(e.id for e in inbox if is_from_board(e.body(), keys, folder, loop_id) is False)


def unchecked_ids(inbox: list[InboxEntry], loop_id: str, folder: Path) -> frozenset[str]:
    """The same, as a loop can tell: with the key of this loop alone."""
    key = read_loop_key(folder)
    return frozenset(entry.id for entry in inbox if is_signed(entry.body(), key, loop_id) is False)
