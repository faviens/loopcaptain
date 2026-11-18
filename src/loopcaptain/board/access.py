"""Who may use the board: the browser that opened the address `serve` printed.

`serve` makes a random key at every start and prints an address that carries it. Opening that
address sets a cookie and leads on to the clean address; every other request needs the cookie.
The address works once: the first browser gets a cookie of its own random value, any later one
nothing.
The key lives in this process only, so a restart makes a new one. The address is relative, so
it works the same under a host name a proxy on this machine forwards.
"""

from __future__ import annotations

import hmac
import secrets
import threading
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


@dataclass
class Session:
    """The key of one board process, and the cookie it issues once, to the first browser that
    opens the printed address. The cookie is its own random value, so the key, once seen, does
    not make it."""

    key: str = field(default_factory=new_key, repr=False)
    cookie_name: str = COOKIE_NAME
    cookie: str | None = field(default=None, repr=False)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    @property
    def entry_path(self) -> str:
        """The path of the address `serve` prints."""
        return f"{ENTER_PATH}?key={quote(self.key)}"

    @property
    def spent(self) -> bool:
        return self.cookie is not None

    def opens(self, given: str) -> bool:
        return hmac.compare_digest(given.encode(), self.key.encode())

    def issue(self) -> str | None:
        """The cookie for the first browser; None once one was issued. Under a lock, since two
        requests can arrive at once on the server's threads."""
        with self.lock:
            if self.cookie is not None:
                return None
            self.cookie = secrets.token_urlsafe(KEY_BYTES)
            return self.cookie

    def admits(self, cookies: Mapping[str, str]) -> bool:
        if self.cookie is None:
            return False
        return hmac.compare_digest(cookies.get(self.cookie_name, "").encode(), self.cookie.encode())


def is_open(path: str) -> bool:
    """Whether a path is served without the cookie: the entry itself, the stylesheet, script and font."""
    return path == ENTER_PATH or path.startswith(STATIC_PREFIX)


def local_path(target: str) -> str:
    """Where the entry leads on to: a path on this board, never another site."""
    plain = target.startswith("/") and not target.startswith(("//", "/\\")) and "\\" not in target
    return target if plain and target.isprintable() else "/"
