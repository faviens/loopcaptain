"""The Telegram bridge: a message when a loop needs the person, and their answer back into its inbox.

Only chats in `telegram.chats` are written to or listened to. An answer goes through the same
checks and ends in the same signed inbox line as the board's forms (`board/answer.py`). Nothing
from a chat can start a loop or run anything. What it remembers (the last update read, the
alerts sent, which button means what) lives in `telegram.json` in the board's state folder.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import quote

from loopcaptain.board.answer import send_reply, send_stop
from loopcaptain.board.discover import Config, LoopView, find_loop, load_all, load_loop
from loopcaptain.board.steer import write_private
from loopcaptain.notify.alerts import SETTLED, Alert, alert_of, alerts_of, to_send
from loopcaptain.notify.settings import TelegramSettings
from loopcaptain.notify.telegram import Bot, Json, TelegramError
from loopcaptain.protocol.store import StoreError

log = logging.getLogger("loopcaptain.telegram")

STATE_FILE = "telegram.json"
#: How many buttons and shown questions are remembered; older ones are dropped first.
KEEP = 500
#: A question longer than this is cut, so the link after it survives Telegram's 4096 characters.
MAX_QUESTION = 3000
#: How long `--pair` waits for the code.
PAIR_WAIT_S = 300
MAX_CHOICES = 8
BACKOFF_S = (5, 15, 60)
STATUS_REPLY_LIMIT = 40


@dataclass(frozen=True)
class Memory:
    offset: int = 0
    sent: tuple[str, ...] = ()
    started: bool = False
    #: button id -> what it does: {"do": "reply"|"stop", "repo", "loop", "question", "choice"}
    buttons: dict[str, dict[str, str]] = field(default_factory=dict)
    #: message id -> the question it showed, so a reply in words can answer it
    asked: dict[str, dict[str, str]] = field(default_factory=dict)


def recent(items: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    return dict(list(items.items())[-KEEP:])


def read_memory(path: Path) -> Memory:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Memory()
    except (OSError, ValueError) as error:
        log.warning("%s unreadable, starting afresh: %s", path.name, type(error).__name__)
        return Memory()
    if not isinstance(data, dict):
        log.warning("%s is not an object, starting afresh", path.name)
        return Memory()
    try:
        return memory_of(data)
    except (TypeError, ValueError, AttributeError) as error:
        log.warning("%s malformed, starting afresh: %s", path.name, type(error).__name__)
        return Memory()


def memory_of(data: dict[str, Any]) -> Memory:
    return Memory(
        offset=int(data.get("offset", 0)),
        sent=tuple(data.get("sent", ())),
        started=bool(data.get("started", False)),
        buttons=dict(data.get("buttons", {})),
        asked=dict(data.get("asked", {})),
    )


def write_memory(path: Path, memory: Memory) -> None:
    data = {
        "offset": memory.offset,
        "sent": list(memory.sent),
        "started": memory.started,
        "buttons": recent(memory.buttons),
        "asked": recent(memory.asked),
    }
    # A crash mid-write must not lose what was sent and read: write aside, then swap in.
    aside = path.with_suffix(".json.tmp")
    write_private(aside, json.dumps(data, indent=1))
    os.replace(aside, path)


def loop_link(settings: TelegramSettings, alert: Alert) -> str:
    if not settings.board_url:
        return ""
    return f"{settings.board_url}/loop/{quote(alert.repo.key)}/{quote(alert.loop_id)}"


def message_text(settings: TelegramSettings, alert: Alert) -> str:
    last = alert.state.last_round
    asked = alert.question.round if alert.question else None
    round_ = asked or (last.number if last else None)
    lines = [alert.headline, alert.repo.key + (f" · round {round_}" if round_ else "")]
    if settings.text == "full":
        if alert.question:
            text = alert.question.text
            lines += ["", text if len(text) <= MAX_QUESTION else text[:MAX_QUESTION] + "…"]
            if not alert.question.options:
                lines.append("Reply to this message to answer.")
        elif alert.state.last_line and alert.status in ("stalled", "failed"):
            lines += ["", alert.state.last_line]
    link = loop_link(settings, alert)
    return "\n".join([*lines, *(["", link] if link else [])])


class Bridge:
    def __init__(
        self,
        bot: Bot,
        settings: TelegramSettings,
        config: Callable[[], Config],
        state_dir: Path,
    ) -> None:
        self.bot = bot
        self.settings = settings
        self.config = config
        self.path = state_dir / STATE_FILE
        self.memory = read_memory(self.path)

    def save(self, memory: Memory) -> None:
        self.memory = memory
        write_memory(self.path, memory)

    def button(self, memory: Memory, label: str, action: dict[str, str]) -> tuple[Memory, Json]:
        ident = secrets.token_hex(6)
        return replace(memory, buttons={**memory.buttons, ident: action}), {
            "text": label,
            "callback_data": ident,
        }

    def buttons_for(self, memory: Memory, alert: Alert) -> tuple[Memory, list[list[Json]]]:
        where = {"repo": alert.repo.key, "loop": alert.loop_id}
        rows: list[list[Json]] = []
        question = alert.question
        if self.settings.text == "full" and question and question.id:
            for option in question.options[:MAX_CHOICES]:
                action = {**where, "do": "reply", "question": question.id, "choice": option.id}
                memory, pressed = self.button(memory, option.label, action)
                rows.append([pressed])
        if alert.status not in SETTLED and not alert.state.stop_requested:
            # A stop is pressed on what the message said; once the loop has moved on, it is refused.
            action = {**where, "do": "stop", "news": alert.key}
            memory, pressed = self.button(memory, "Stop after this round", action)
            rows.append([pressed])
        return memory, rows

    def notify(self) -> int:
        """Send every alert not sent before to every allowed chat; return how many went out."""
        alerts = alerts_of(load_all(self.config()))
        sent = frozenset(self.memory.sent)
        fresh = to_send(alerts, sent, first_run=not self.memory.started)
        # Only a loop's current news is worth remembering: news it has moved past cannot come back
        # under the same key, except a stall in the same round, which is news again.
        news = {alert.key for alert in fresh}
        current = tuple(alert.key for alert in alerts if alert.key not in news)
        self.save(replace(self.memory, started=True, sent=current))
        for alert in fresh:
            memory = self.deliver(self.memory, alert)
            self.save(replace(memory, sent=(*memory.sent, alert.key)))
        return len(fresh)

    def deliver(self, memory: Memory, alert: Alert) -> Memory:
        """Send one alert to every chat. A chat that refuses for good (it blocked the bot) is logged
        and skipped. Any other failure, such as no network, propagates: the alert stays unsent and
        is tried again, so a chat that already got it may get it twice, but none misses it."""
        memory, rows = self.buttons_for(memory, alert)
        self.save(memory)  # the buttons work as soon as any chat shows them
        text = message_text(self.settings, alert)
        for chat in sorted(self.settings.chats):
            try:
                message_id = self.bot.send(chat, text, rows)
            except TelegramError as problem:
                if not problem.for_good:
                    raise
                log.warning("one chat refuses the bot: %s", problem)
                continue
            if alert.question and alert.question.id and self.settings.text == "full":
                shown = {"repo": alert.repo.key, "loop": alert.loop_id, "question": alert.question.id}
                memory = replace(memory, asked={**memory.asked, f"{chat}:{message_id}": shown})
        return memory

    def find(self, repo_key: str, loop_id: str) -> LoopView | None:
        found = find_loop(self.config(), repo_key, loop_id)
        return load_loop(found[0], loop_id) if found else None

    def act(self, action: dict[str, str], text: str = "") -> str:
        view = self.find(action.get("repo", ""), action.get("loop", ""))
        if view is None:
            return "That loop is no longer on the board."
        news = action.get("news")
        if news is not None:
            now = alert_of(view)
            if now is None or now.key != news:
                return "Not sent: the loop has moved on since that message. Send /status."
        try:
            if action.get("do") == "stop":
                return send_stop(view.repo, view.loop_id, view.state)
            return send_reply(
                view.repo,
                view.loop_id,
                view.state,
                text,
                action.get("choice", ""),
                action.get("question", ""),
            )
        except StoreError as problem:
            return str(problem)

    def status_text(self) -> str:
        views = load_all(self.config())
        if not views:
            return "No loops on the board."
        lines = [
            f"{view.title} · {view.repo.key}: {view.state.status if view.state else 'unreadable'}"
            for view in views
        ]
        more = len(lines) - STATUS_REPLY_LIMIT
        return "\n".join(lines[:STATUS_REPLY_LIMIT] + ([f"and {more} more"] if more > 0 else []))

    def handle(self, update: Json) -> None:
        callback = update.get("callback_query")
        if callback:
            self.handle_press(callback)
            return
        message = update.get("message") or {}
        chat = self.allowed(message.get("chat"))
        if chat is None:
            log.info("ignored a message from a chat that is not allowed")
            return
        self.handle_message(chat, message)

    def allowed(self, chat: object) -> int | None:
        """The chat's id when it is listed and private: in a group, every member could steer."""
        if not isinstance(chat, dict) or chat.get("type") != "private":
            return None
        ident = chat.get("id")
        return ident if isinstance(ident, int) and ident in self.settings.chats else None

    def handle_press(self, callback: Json) -> None:
        chat = self.allowed((callback.get("message") or {}).get("chat"))
        action = self.memory.buttons.get(str(callback.get("data", ""))) if chat is not None else None
        if chat is None:
            log.info("ignored a button from a chat that is not allowed, or from a message gone")
        answer = self.act(action) if action else "That button has expired; open the board."
        try:
            self.bot.acknowledge(str(callback.get("id", "")), answer)
        except TelegramError as problem:  # a press from long ago can no longer be acknowledged
            log.info("%s", problem)
        if chat is not None:
            self.bot.send(chat, answer)

    def handle_message(self, chat: int, message: Json) -> None:
        text = str(message.get("text") or "").strip()
        replied = (message.get("reply_to_message") or {}).get("message_id")
        shown = self.memory.asked.get(f"{chat}:{replied}") if replied else None
        if shown:
            self.bot.send(chat, self.act({**shown, "do": "reply"}, text))
        elif text.startswith("/status"):
            self.bot.send(chat, self.status_text())
        else:
            self.bot.send(chat, "Send /status for every loop, or reply to a question's message to answer it.")

    def poll(self) -> None:
        for update in self.read_updates():
            try:
                self.handle(update)
            except Exception as problem:
                log.warning("one update failed: %s", type(problem).__name__)

    def read_updates(self) -> list[Json]:
        """The next updates, all marked read before any is handled, so a bad one is never read twice."""
        updates = []
        for update in self.bot.updates(self.memory.offset):
            if not isinstance(update, dict) or not isinstance(update.get("update_id"), int):
                log.warning("skipped an update without an id")
                continue
            self.save(replace(self.memory, offset=update["update_id"] + 1))
            updates.append(update)
        return updates

    def pair(self, code: str, wait_s: float = PAIR_WAIT_S) -> int:
        """Wait for `code` from a private chat and return that chat's id; anything else is ignored."""
        until = time.monotonic() + wait_s
        while True:
            for update in self.read_updates():
                message = update.get("message") or {}
                chat = message.get("chat") or {}
                words = str(message.get("text") or "").split()
                if chat.get("type") == "private" and code in words:
                    self.bot.send(int(chat["id"]), "Paired. This chat now hears from your loops.")
                    return int(chat["id"])
            if time.monotonic() >= until:
                raise StoreError("no chat sent the code in time")

    @staticmethod
    def backoff(failures: int) -> int:
        return BACKOFF_S[min(failures, len(BACKOFF_S) - 1)]

    def run(self, rounds: int | None = None) -> None:
        """Notify, then wait for presses and replies, over and over; `rounds` bounds it for tests."""
        failures = 0
        done = 0
        while rounds is None or done < rounds:
            done += 1
            try:
                self.notify()
                self.poll()
                failures = 0
            except (TelegramError, StoreError) as problem:
                wait = self.backoff(failures)
                failures += 1
                log.warning("%s; trying again in %s s", problem, wait)
                time.sleep(wait)
            except Exception as problem:
                wait = self.backoff(failures)
                failures += 1
                # The type only: a message could quote a request, and a request carries the token.
                log.warning("unexpected %s; trying again in %s s", type(problem).__name__, wait)
                time.sleep(wait)
