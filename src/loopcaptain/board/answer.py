"""What the person sends a loop, wherever they send it from: the board's forms or a chat.

Both routes end in the same signed line of the loop's `inbox.jsonl`, checked the same way: a
choice must still be offered, a reply must not be empty or too long, a stop is sent once.
"""

from __future__ import annotations

from loopcaptain.board.discover import Repo
from loopcaptain.protocol import store
from loopcaptain.protocol.signing import board_key
from loopcaptain.protocol.state import LoopState
from loopcaptain.protocol.store import StoreError

MAX_REPLY_CHARS = 20_000
SENT_REPLY = "Sent. The loop reads it at its next round."
SENT_STOP = "Stop sent. The loop ends after its current round."
STOP_WAITING = "A stop is already waiting for the loop."


def send_reply(
    repo: Repo, loop_id: str, state: LoopState | None, text: str = "", choice: str = "", question: str = ""
) -> str:
    """Append a reply and say so; raise `StoreError` with the reason when nothing was sent.

    `question`, when given, is the id of the question the person saw: a reply to a question that
    has since closed or been replaced is refused rather than read as an answer to the new one.
    """
    asked = state.question if state else None
    if question and (asked is None or asked.id != question):
        raise StoreError("Nothing was sent: that question is no longer open.")
    picked = next((option for option in asked.options if option.id == choice), None) if asked else None
    if choice and picked is None:
        raise StoreError("Nothing was sent: that choice is no longer offered.")
    message = text.strip() or (picked.label if picked else "")
    if not message:
        raise StoreError("Nothing was sent: the reply was empty.")
    if len(message) > MAX_REPLY_CHARS:
        raise StoreError(f"Nothing was sent: over {MAX_REPLY_CHARS} characters.")
    last = state.last_round if state else None
    round_ = asked.round if asked and asked.round else (last.number if last else None)
    store.append_inbox(
        repo.path,
        loop_id,
        "reply",
        message,
        round_,
        key=board_key(),
        question=asked.id if asked else None,
        choice=picked.id if picked else None,
    )
    return SENT_REPLY


def send_stop(repo: Repo, loop_id: str, state: LoopState | None) -> str:
    """Append a stop unless one is already waiting; say which."""
    if state and state.stop_requested:
        return STOP_WAITING
    store.append_inbox(repo.path, loop_id, "stop", key=board_key())
    return SENT_STOP
