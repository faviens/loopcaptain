"""The few Telegram Bot API calls the bridge needs, over HTTPS with the standard library.

The board calls out and long-polls for updates; Telegram never calls in, so nothing on this
machine listens for it. The bot token sits in the request path: no error, log line or message
may carry the URL, so every failure is reported by method name only.
"""

from __future__ import annotations

import http.client
import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

log = logging.getLogger("loopcaptain.telegram")

API = "https://api.telegram.org"
TOKEN_ENV = "LOOPCAPTAIN_TELEGRAM_TOKEN"
#: Seconds Telegram holds a getUpdates call open when nothing happens.
POLL_S = 25
#: Seconds the HTTP call may take beyond the poll.
SLACK_S = 10
#: Telegram's limit for a message's text.
MAX_TEXT = 4096

Json = dict[str, Any]
#: Calls one API method with a JSON body and returns the decoded answer; tests pass a fake.
Transport = Callable[[str, Json, float], Json]


#: Answers that will not change on a retry: the person blocked the bot or the chat is gone.
FOR_GOOD = ("Forbidden", "chat not found")


class TelegramError(Exception):
    """A call failed. The text never contains the token. `for_good`: retrying will not help."""

    def __init__(self, text: str, for_good: bool = False) -> None:
        super().__init__(text)
        self.for_good = for_good


def https_transport(token: str) -> Transport:
    def call(method: str, payload: Json, timeout: float) -> Json:
        request = urllib.request.Request(
            f"{API}/bot{token}/{method}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                answer: Json = json.loads(response.read())
        except urllib.error.HTTPError as error:
            answer = read_error_body(error)
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as error:
            raise TelegramError(f"{method}: {type(error).__name__}") from None
        return answer

    return call


def read_error_body(error: urllib.error.HTTPError) -> Json:
    try:
        body: Json = json.loads(error.read())
    except (OSError, ValueError):
        body = {"ok": False, "description": f"HTTP {error.code}"}
    return body


class Bot:
    def __init__(self, transport: Transport) -> None:
        self.transport = transport

    def call(self, method: str, payload: Json, timeout: float = SLACK_S) -> Any:
        answer = self.transport(method, payload, timeout)
        if not isinstance(answer, dict):
            raise TelegramError(f"{method}: an answer that is not an object")
        if not answer.get("ok"):
            description = str(answer.get("description", "refused"))
            raise TelegramError(f"{method}: {description}", any(mark in description for mark in FOR_GOOD))
        return answer.get("result")

    def send(self, chat: int, text: str, buttons: list[list[Json]] | None = None) -> int:
        payload: Json = {
            "chat_id": chat,
            "text": text[:MAX_TEXT],
            "link_preview_options": {"is_disabled": True},
        }
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}
        result = self.call("sendMessage", payload)
        return int(result["message_id"])

    def updates(self, offset: int, poll_s: int = POLL_S) -> list[Json]:
        payload: Json = {
            "offset": offset,
            "timeout": poll_s,
            "allowed_updates": ["message", "callback_query"],
        }
        result = self.call("getUpdates", payload, timeout=poll_s + SLACK_S)
        return list(result or [])

    def acknowledge(self, callback_id: str, text: str) -> None:
        self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:200]})
