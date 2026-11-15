"""Which loops need telling about, from the status the board already derives.

An alert has a key that changes only when there is something new to say: a new question, a
new round that failed, a loop that stalled again. A channel sends each key once.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from loopcaptain.board.discover import LoopView, Repo
from loopcaptain.protocol.state import LoopState, OpenQuestion

#: The statuses worth a message, in words for the message.
ALERT_TEXT: dict[str, str] = {
    "waiting": "needs your answer",
    "asks": "asks you something",
    "failed": "failed",
    "stalled": "has gone silent",
    "capped": "reached a cap",
    "done": "is done",
    "stopped": "stopped",
}
#: Statuses that end a loop: the first run of a channel records them without sending.
SETTLED = frozenset({"done", "stopped", "capped", "failed"})
#: An open question, whether the loop stands still for it ("waiting") or asked in passing ("asks").
ASKING = frozenset({"waiting", "asks"})


@dataclass(frozen=True)
class Alert:
    repo: Repo
    loop_id: str
    title: str
    status: str
    key: str
    state: LoopState

    @property
    def question(self) -> OpenQuestion | None:
        return self.state.question if self.status in ASKING else None

    @property
    def headline(self) -> str:
        return f"{self.title} {ALERT_TEXT[self.status]}"


def question_mark(question: OpenQuestion | None) -> str:
    if question is None:
        return "-"
    return question.id or hashlib.sha256(question.text.encode()).hexdigest()[:12]


def alert_of(view: LoopView) -> Alert | None:
    state = view.state
    if state is None:
        return None
    kind = "asks" if state.question is not None and state.status not in ASKING | SETTLED else state.status
    if kind not in ALERT_TEXT:
        return None
    last = state.last_round
    round_mark = last.number if last else 0
    mark = question_mark(state.question) if kind in ASKING else "-"
    # One question is one message, whether the loop then stands still for it or not.
    key = f"{view.repo.key}/{view.loop_id}:{'question' if kind in ASKING else kind}:{round_mark}:{mark}"
    return Alert(view.repo, view.loop_id, view.title, kind, key, state)


def alerts_of(views: list[LoopView]) -> list[Alert]:
    return [alert for alert in map(alert_of, views) if alert is not None]


def to_send(alerts: list[Alert], sent: frozenset[str], first_run: bool) -> list[Alert]:
    """The alerts not sent before. On a channel's first run, only a loop that waits for an answer is
    news; a loop that ended last week is not."""
    fresh = [alert for alert in alerts if alert.key not in sent]
    return [alert for alert in fresh if not (first_run and alert.status in SETTLED)]
