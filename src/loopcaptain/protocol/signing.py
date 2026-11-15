"""The board's mark on the inbox: an HMAC over each line it writes, with a key no repository holds.

The inbox is a plain file in the loop's repository, so an agent that can write files there could
add a `reply` that reads as the person or a `stop` that ends the run. The board signs every line
with a key kept in the user's config folder, outside every watched repository; a line without a
valid `sig` is "not from the board". This protects against agents confined to their repository,
not against a process with the user's full file access, which can read the key too.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from loopcaptain.protocol.models import InboxEntry

log = logging.getLogger("loopcaptain.signing")

KEY_ENV = "LOOPCAPTAIN_INBOX_KEY"
DEFAULT_KEY = Path("~/.config/loopcaptain/inbox.key")
KEY_BYTES = 32
PRIVATE_MODE = 0o600
PRIVATE_DIR_MODE = 0o700


def key_path() -> Path:
    return Path(os.environ.get(KEY_ENV) or DEFAULT_KEY).expanduser()


def read_key() -> bytes | None:
    """The board's key, or None where this machine has none yet or it cannot be read."""
    try:
        key = bytes.fromhex(key_path().read_text(encoding="utf-8").strip())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        log.warning("the inbox key at %s cannot be read: %s", key_path(), error)
        return None
    if len(key) < KEY_BYTES:
        log.warning("the inbox key at %s is too short; it is not used", key_path())
        return None
    return key


def board_key() -> bytes:
    """The board's key, created readable by this user only on first use."""
    found = read_key()
    if found:
        return found
    path = key_path()
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
        existing = read_key()
        if existing is None:
            raise
        return existing
    finally:
        draft.unlink(missing_ok=True)
    log.info("created the inbox key at %s", path)
    return key


def canonical(entry: dict[str, Any]) -> bytes:
    """The bytes that are signed: the line without `sig`, keys sorted, no spaces."""
    body = {key: value for key, value in entry.items() if key != "sig"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign(entry: dict[str, Any], key: bytes) -> str:
    return hmac.new(key, canonical(entry), hashlib.sha256).hexdigest()


def is_signed(entry: dict[str, Any], key: bytes | None, loop_id: str | None = None) -> bool | None:
    """True if the board wrote this line for this loop, False if not, None where there is no key.

    The line names its loop, so a signed line copied into another loop's inbox is not signed there.
    """
    if key is None:
        return None
    given = entry.get("sig")
    if loop_id is not None and entry.get("loop") != loop_id:
        return False
    return isinstance(given, str) and hmac.compare_digest(given, sign(entry, key))


def untrusted_ids(inbox: list[InboxEntry], loop_id: str) -> frozenset[str]:
    """The inbox entries whose signature fails. Without a key on this machine nothing can be told apart."""
    key = read_key()
    return frozenset(entry.id for entry in inbox if is_signed(entry.body(), key, loop_id) is False)
