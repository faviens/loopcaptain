"""The `telegram:` part of the board's config file, and the one edit pairing makes to it.

```yaml
telegram:
  chats: [123456789]          # who may read and steer; pairing adds to it
  text: minimal               # minimal: loop name and status only; full: the question and its choices
  board_url: https://box.example.ts.net   # optional: each message links to the loop's page
```

The bot token is not in the file: it comes from `LOOPCAPTAIN_TELEGRAM_TOKEN`. Pairing rewrites the
file, as `loopcaptain watch` does, so comments in it are not kept.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from loopcaptain.protocol.store import StoreError

TextMode = Literal["minimal", "full"]
SECTION = "telegram"


@dataclass(frozen=True)
class TelegramSettings:
    chats: frozenset[int] = frozenset()
    text: TextMode = "minimal"
    board_url: str = ""


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, yaml.YAMLError) as error:
        raise StoreError(f"{path.name}: {error}") from error
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise StoreError(f"{path.name}: expected a mapping")
    return data


def parse_settings(data: dict[str, Any], name: str = "config") -> TelegramSettings:
    section = data.get(SECTION) or {}
    if not isinstance(section, dict):
        raise StoreError(f"{name}: `{SECTION}` must be a mapping")
    chats = section.get("chats") or []
    if not isinstance(chats, list) or not all(
        isinstance(chat, int) and not isinstance(chat, bool) for chat in chats
    ):
        raise StoreError(f"{name}: `{SECTION}.chats` must be a list of chat ids")
    text = section.get("text", "minimal")
    if text not in ("minimal", "full"):
        raise StoreError(f"{name}: `{SECTION}.text` is `minimal` or `full`")
    board_url = section.get("board_url", "") or ""
    if not isinstance(board_url, str) or (board_url and not board_url.startswith("https://")):
        raise StoreError(f"{name}: `{SECTION}.board_url` must start with https://")
    return TelegramSettings(frozenset(chats), text, board_url.rstrip("/"))


def load_settings(path: Path | None) -> TelegramSettings:
    return parse_settings(read_yaml(path), path.name) if path else TelegramSettings()


def add_chat(path: Path, chat: int) -> None:
    """Allow one more chat, keeping the rest of the file."""
    data = read_yaml(path)
    section = data.get(SECTION) or {}
    if not isinstance(section, dict):
        raise StoreError(f"{path.name}: `{SECTION}` must be a mapping")
    chats = list(section.get("chats") or [])
    updated = {**data, SECTION: {**section, "chats": chats if chat in chats else [*chats, chat]}}
    path.parent.mkdir(parents=True, exist_ok=True)
    aside = path.with_name(path.name + ".tmp")
    aside.write_text(yaml.safe_dump(updated, sort_keys=False), encoding="utf-8")
    os.replace(aside, path)
