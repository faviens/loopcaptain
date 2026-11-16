"""Who may use the board: the browser that opened the address `serve` printed.

`serve` makes a random key at every start and prints an address that carries it. Opening that
address sets a cookie and leads on to the clean address; every other request needs the cookie.
The key lives in this process only, so a restart makes a new one. The address is relative, so
it works the same under a host name a proxy on this machine forwards.
"""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import quote

#: The only address the board listens on.
HOST = "127.0.0.1"
#: The page that takes the key and sets the cookie; it and the static files are open to anyone.
ENTER_PATH = "/enter"
STATIC_PREFIX = "/static/"
COOKIE_NAME = "loopcaptain"
KEY_BYTES = 32


def new_key() -> str:
    return secrets.token_urlsafe(KEY_BYTES)


@dataclass(frozen=True)
class Session:
    """The key of one board process and the cookie that proves a browser was given it."""

    key: str = field(default_factory=new_key, repr=False)
    cookie_name: str = COOKIE_NAME

    @property
    def cookie_value(self) -> str:
        """What the cookie holds: made from the key, so neither a page nor the cookie shows the key."""
        return hmac.new(self.key.encode(), b"loopcaptain session cookie", "sha256").hexdigest()

    @property
    def entry_path(self) -> str:
        """The path of the address `serve` prints."""
        return f"{ENTER_PATH}?key={quote(self.key)}"

    def opens(self, given: str) -> bool:
        return hmac.compare_digest(given.encode(), self.key.encode())

    def admits(self, cookies: Mapping[str, str]) -> bool:
        given = cookies.get(self.cookie_name, "")
        return hmac.compare_digest(given.encode(), self.cookie_value.encode())


def is_open(path: str) -> bool:
    """Whether a path is served without the cookie: the entry itself, the stylesheet, script and font."""
    return path == ENTER_PATH or path.startswith(STATIC_PREFIX)


def local_path(target: str) -> str:
    """Where the entry leads on to: a path on this board, never another site."""
    plain = target.startswith("/") and not target.startswith(("//", "/\\")) and "\\" not in target
    return target if plain and target.isprintable() else "/"
