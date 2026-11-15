"""The Telegram bridge against a fake Telegram: who hears what, and what an answer writes."""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any

import pytest

from loopcaptain.board.discover import Config
from loopcaptain.notify.bridge import Bridge
from loopcaptain.notify.settings import TelegramSettings, add_chat, load_settings, parse_settings
from loopcaptain.notify.telegram import Bot, TelegramError
from loopcaptain.protocol import store
from loopcaptain.protocol.store import StoreError

ME = 1001
STRANGER = 666
OPTIONS = [{"id": "seat", "label": "Per seat"}, {"id": "site", "label": "Per site"}]


class FakeTelegram:
    """Answers like the Bot API and records what the bridge sent."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.toasts: list[str] = []
        self.inbox: list[dict[str, Any]] = []
        self.next_id = 1

    def __call__(self, method: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        if method == "sendMessage":
            self.sent.append(payload)
            self.next_id += 1
            return {"ok": True, "result": {"message_id": self.next_id}}
        if method == "getUpdates":
            waiting = [
                u
                for u in self.inbox
                if not isinstance(u["update_id"], int) or u["update_id"] >= payload["offset"]
            ]
            return {"ok": True, "result": waiting}
        if method == "answerCallbackQuery":
            self.toasts.append(payload["text"])
            return {"ok": True, "result": True}
        return {"ok": False, "description": "Not Found"}

    def press(self, chat: int, data: str, kind: str = "private") -> None:
        update_id = len(self.inbox) + 1
        callback = {"id": f"cb{update_id}", "data": data, "message": {"chat": {"id": chat, "type": kind}}}
        self.inbox.append({"update_id": update_id, "callback_query": callback})

    def say(self, chat: int, text: str, reply_to: int | None = None, kind: str = "private") -> None:
        message: dict[str, Any] = {"chat": {"id": chat, "type": kind}, "text": text}
        if reply_to:
            message["reply_to_message"] = {"message_id": reply_to}
        self.inbox.append({"update_id": len(self.inbox) + 1, "message": message})


@pytest.fixture
def fake() -> FakeTelegram:
    return FakeTelegram()


def bridge_for(scan: Path, tmp_path: Path, fake: FakeTelegram, text: str = "full") -> Bridge:
    settings = TelegramSettings(chats=frozenset({ME}), text=text, board_url="https://box.example.ts.net")  # type: ignore[arg-type]
    return Bridge(Bot(fake), settings, lambda: Config(repos=(scan,)), tmp_path / "state")


def ask(helper: types.ModuleType, scan: Path) -> None:
    question = {"round": 3, "id": "price", "text": "Per seat or per site?", "options": OPTIONS}
    helper.emit("scan", "question", question, scan)


def test_a_question_reaches_the_allowed_chat_once_with_its_choices(
    scan: Path, tmp_path: Path, helper: types.ModuleType, fake: FakeTelegram
) -> None:
    ask(helper, scan)
    bridge = bridge_for(scan, tmp_path, fake)

    assert bridge.notify() == 1
    assert bridge.notify() == 0
    [message] = fake.sent
    labels = [row[0]["text"] for row in message["reply_markup"]["inline_keyboard"]]
    assert message["chat_id"] == ME
    assert "Market scan asks you something" in message["text"]
    assert "Per seat or per site?" in message["text"]
    assert "some-repo · round 3" in message["text"]
    assert "https://box.example.ts.net/loop/some-repo/scan" in message["text"]
    assert labels == ["Per seat", "Per site", "Stop after this round"]


def test_minimal_text_names_the_loop_but_not_the_question(
    scan: Path, tmp_path: Path, helper: types.ModuleType, fake: FakeTelegram
) -> None:
    ask(helper, scan)
    bridge_for(scan, tmp_path, fake, text="minimal").notify()

    [message] = fake.sent
    labels = [row[0]["text"] for row in message["reply_markup"]["inline_keyboard"]]
    assert "Per seat or per site?" not in message["text"]
    assert labels == ["Stop after this round"]


def test_a_pressed_choice_writes_the_same_signed_reply_as_the_board(
    scan: Path, tmp_path: Path, helper: types.ModuleType, fake: FakeTelegram
) -> None:
    ask(helper, scan)
    bridge = bridge_for(scan, tmp_path, fake)
    bridge.notify()
    seat = fake.sent[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]

    fake.press(ME, seat)
    bridge.poll()

    [entry] = store.read_inbox(scan, "scan")[0]
    assert (entry.kind, entry.text, entry.question, entry.choice) == ("reply", "Per seat", "price", "seat")
    assert entry.sig
    assert fake.toasts == ["Sent. The loop reads it at its next round."]


def test_a_reply_in_words_answers_the_question_of_that_message(
    scan: Path, tmp_path: Path, helper: types.ModuleType, fake: FakeTelegram
) -> None:
    helper.emit("scan", "question", {"round": 2, "id": "who", "text": "Who reads it?"}, scan)
    bridge = bridge_for(scan, tmp_path, fake)
    bridge.notify()

    fake.say(ME, "The board of directors", reply_to=fake.next_id)
    bridge.poll()

    [entry] = store.read_inbox(scan, "scan")[0]
    assert (entry.text, entry.question) == ("The board of directors", "who")


def test_an_answer_to_a_question_that_closed_is_refused(
    scan: Path, tmp_path: Path, helper: types.ModuleType, fake: FakeTelegram
) -> None:
    ask(helper, scan)
    bridge = bridge_for(scan, tmp_path, fake)
    bridge.notify()
    seat = fake.sent[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    helper.emit("scan", "question", {"round": 2, "id": "other", "text": "Something else?"}, scan)

    fake.press(ME, seat)
    bridge.poll()

    assert store.read_inbox(scan, "scan") == ([], [])
    assert fake.toasts == ["Nothing was sent: that question is no longer open."]


def test_a_stranger_can_neither_press_nor_ask(
    scan: Path, tmp_path: Path, helper: types.ModuleType, fake: FakeTelegram
) -> None:
    ask(helper, scan)
    bridge = bridge_for(scan, tmp_path, fake)
    bridge.notify()
    stop = fake.sent[0]["reply_markup"]["inline_keyboard"][-1][0]["callback_data"]

    fake.press(STRANGER, stop)
    fake.say(STRANGER, "/status")
    bridge.poll()

    assert store.read_inbox(scan, "scan") == ([], [])
    assert all(message["chat_id"] == ME for message in fake.sent)


def test_stop_is_sent_once(scan: Path, tmp_path: Path, helper: types.ModuleType, fake: FakeTelegram) -> None:
    ask(helper, scan)
    bridge = bridge_for(scan, tmp_path, fake)
    bridge.notify()
    stop = fake.sent[0]["reply_markup"]["inline_keyboard"][-1][0]["callback_data"]

    fake.press(ME, stop)
    fake.press(ME, stop)
    bridge.poll()

    assert [entry.kind for entry in store.read_inbox(scan, "scan")[0]] == ["stop"]
    assert fake.toasts[1] == "A stop is already waiting for the loop."


def test_status_lists_every_loop(scan: Path, tmp_path: Path, fake: FakeTelegram) -> None:
    bridge = bridge_for(scan, tmp_path, fake)

    fake.say(ME, "/status")
    bridge.poll()

    assert fake.sent[-1]["text"] == "Market scan · some-repo: running"


def test_the_first_run_skips_a_loop_that_ended_before_it(
    scan: Path, tmp_path: Path, helper: types.ModuleType, fake: FakeTelegram
) -> None:
    helper.emit("scan", "round_finished", {"round": 2, "verdict": "done", "summary": "Closed."}, scan)
    bridge = bridge_for(scan, tmp_path, fake)

    assert bridge.notify() == 0


def test_what_was_sent_survives_a_restart(
    scan: Path, tmp_path: Path, helper: types.ModuleType, fake: FakeTelegram
) -> None:
    ask(helper, scan)
    bridge_for(scan, tmp_path, fake).notify()

    again = bridge_for(scan, tmp_path, fake)

    assert again.notify() == 0
    assert (tmp_path / "state" / "telegram.json").stat().st_mode & 0o777 == 0o600


def test_pairing_takes_the_code_only_from_a_private_chat(
    scan: Path, tmp_path: Path, fake: FakeTelegram
) -> None:
    fake.say(STRANGER, "abc123", kind="group")
    fake.say(ME, "/start abc123")

    assert bridge_for(scan, tmp_path, fake).pair("abc123", wait_s=0) == ME


def test_pairing_gives_up(scan: Path, tmp_path: Path, fake: FakeTelegram) -> None:
    with pytest.raises(StoreError, match="no chat"):
        bridge_for(scan, tmp_path, fake).pair("abc123", wait_s=0)


def test_a_failed_call_names_the_method_and_never_the_token() -> None:
    def refuse(method: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        return {"ok": False, "description": "Unauthorized"}

    with pytest.raises(TelegramError, match=r"^sendMessage: Unauthorized$"):
        Bot(refuse).send(ME, "hello")


def test_pairing_adds_the_chat_and_keeps_the_rest_of_the_config(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("roots: [~/projects]\ntelegram:\n  text: full\n", encoding="utf-8")

    add_chat(path, ME)
    add_chat(path, ME)

    settings = load_settings(path)
    assert (settings.chats, settings.text) == (frozenset({ME}), "full")
    assert "roots" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "section",
    [{"chats": "1001"}, {"chats": [True]}, {"text": "everything"}, {"board_url": "http://box"}, "yes"],
)
def test_a_wrong_telegram_section_is_refused(section: object) -> None:
    with pytest.raises(StoreError, match="telegram"):
        parse_settings({"telegram": section})


def test_the_command_needs_a_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from loopcaptain.cli import main

    monkeypatch.delenv("LOOPCAPTAIN_TELEGRAM_TOKEN", raising=False)

    assert main(["telegram"]) == 1
    assert "LOOPCAPTAIN_TELEGRAM_TOKEN" in capsys.readouterr().err


def test_a_question_that_comes_to_block_is_not_sent_twice(
    scan: Path, tmp_path: Path, helper: types.ModuleType, fake: FakeTelegram
) -> None:
    ask(helper, scan)
    bridge = bridge_for(scan, tmp_path, fake)
    bridge.notify()

    helper.emit("scan", "round_finished", {"round": 2, "verdict": "wait", "summary": "Needs a price."}, scan)

    assert bridge.notify() == 0


def test_a_failing_telegram_is_tried_again_later(
    scan: Path, tmp_path: Path, fake: FakeTelegram, monkeypatch: pytest.MonkeyPatch
) -> None:
    waits: list[float] = []
    monkeypatch.setattr("loopcaptain.notify.bridge.time.sleep", waits.append)

    def down(method: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        raise TelegramError(f"{method}: URLError")

    bridge = bridge_for(scan, tmp_path, fake)
    bridge.bot = Bot(down)
    bridge.run(rounds=3)

    assert waits == [5, 15, 60]


def test_a_chat_that_blocked_the_bot_does_not_stop_the_others(
    scan: Path, tmp_path: Path, helper: types.ModuleType, fake: FakeTelegram
) -> None:
    def blocked_for_one(method: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        if payload.get("chat_id") == STRANGER:
            return {"ok": False, "description": "Forbidden: bot was blocked by the user"}
        return fake(method, payload, timeout)

    ask(helper, scan)
    settings = TelegramSettings(chats=frozenset({ME, STRANGER}), text="full")
    bridge = Bridge(Bot(blocked_for_one), settings, lambda: Config(repos=(scan,)), tmp_path / "state")

    assert bridge.notify() == 1
    assert bridge.notify() == 0
    assert [message["chat_id"] for message in fake.sent] == [ME]


def test_a_stop_from_an_old_message_is_refused_once_the_loop_moved_on(
    scan: Path, tmp_path: Path, helper: types.ModuleType, fake: FakeTelegram
) -> None:
    ask(helper, scan)
    bridge = bridge_for(scan, tmp_path, fake)
    bridge.notify()
    stop = fake.sent[0]["reply_markup"]["inline_keyboard"][-1][0]["callback_data"]
    helper.emit("scan", "question_closed", {"question": "price", "reason": "withdrawn"}, scan)

    fake.press(ME, stop)
    bridge.poll()

    assert store.read_inbox(scan, "scan") == ([], [])
    assert fake.toasts[0].startswith("Not sent: the loop has moved on")


def test_a_broken_memory_file_starts_afresh(scan: Path, tmp_path: Path, fake: FakeTelegram) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "telegram.json").write_text("[1, 2]", encoding="utf-8")

    assert bridge_for(scan, tmp_path, fake).memory.offset == 0


def test_an_answer_that_is_not_an_object_is_a_telegram_error() -> None:
    def odd(method: str, payload: dict[str, Any], timeout: float) -> Any:
        return ["not", "an", "object"]

    with pytest.raises(TelegramError, match="not an object"):
        Bot(odd).send(ME, "hello")


def test_an_update_without_an_id_is_skipped(scan: Path, tmp_path: Path, fake: FakeTelegram) -> None:
    fake.inbox.append({"message": {"chat": {"id": ME}, "text": "/status"}, "update_id": "x"})
    bridge = bridge_for(scan, tmp_path, fake)

    assert bridge.read_updates() == []


def test_an_alert_that_could_not_be_sent_is_sent_later(
    scan: Path, tmp_path: Path, helper: types.ModuleType, fake: FakeTelegram
) -> None:
    ask(helper, scan)
    bridge = bridge_for(scan, tmp_path, fake)
    bridge.bot = Bot(lambda method, payload, timeout: {"ok": False, "description": "Too Many Requests"})

    with pytest.raises(TelegramError):
        bridge.notify()
    bridge.bot = Bot(fake)

    assert bridge.notify() == 1
    assert len(fake.sent) == 1


def test_a_group_chat_is_not_heard_even_when_listed(
    scan: Path, tmp_path: Path, helper: types.ModuleType, fake: FakeTelegram
) -> None:
    ask(helper, scan)
    bridge = bridge_for(scan, tmp_path, fake)
    bridge.notify()
    stop = fake.sent[0]["reply_markup"]["inline_keyboard"][-1][0]["callback_data"]

    fake.press(ME, stop, kind="group")
    fake.say(ME, "/status", kind="group")
    bridge.poll()

    assert store.read_inbox(scan, "scan") == ([], [])
    assert len(fake.sent) == 1


def test_one_bad_update_does_not_drop_the_next(
    scan: Path, tmp_path: Path, helper: types.ModuleType, fake: FakeTelegram
) -> None:
    ask(helper, scan)
    bridge = bridge_for(scan, tmp_path, fake)
    bridge.notify()
    seat = fake.sent[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]

    def old_press(method: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        if method == "answerCallbackQuery":
            return {"ok": False, "description": "Bad Request: query is too old"}
        if method == "sendMessage" and payload["text"].startswith("Send /status"):
            raise RuntimeError("boom")
        return fake(method, payload, timeout)

    bridge.bot = Bot(old_press)
    fake.say(ME, "hello")
    fake.press(ME, seat)
    bridge.poll()

    assert [entry.choice for entry in store.read_inbox(scan, "scan")[0]] == ["seat"]
    assert fake.sent[-1]["text"] == "Sent. The loop reads it at its next round."


def test_a_long_question_keeps_the_link(
    scan: Path, tmp_path: Path, helper: types.ModuleType, fake: FakeTelegram
) -> None:
    helper.emit("scan", "question", {"round": 2, "id": "long", "text": "Why? " * 2000}, scan)
    bridge_for(scan, tmp_path, fake).notify()

    assert fake.sent[0]["text"].endswith("https://box.example.ts.net/loop/some-repo/scan")
