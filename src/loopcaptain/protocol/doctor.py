"""`loopcaptain doctor`: does a loop listen? Send it a stop and watch whether it takes it and ends.

`validate` checks the files; only a run shows that the inbox is read. The doctor appends a signed
`stop` to the loop's inbox, then waits for the loop to mark it read (`inbox_read`) and to end (a
`round_finished` with verdict `stopped`, or `loop_stopped`). The loop must be running, or be started
while the doctor waits.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from loopcaptain.protocol import store
from loopcaptain.protocol.models import InboxRead, LoopStopped, RoundFinished
from loopcaptain.protocol.signing import board_key

POLL_S = 1.0
#: A round that took the stop ends with `stopped`, or with `done` where it met the goal anyway.
ENDING_VERDICTS = frozenset({"stopped", "done"})


@dataclass(frozen=True)
class Checkup:
    """What the doctor saw, step by step; `passed` only if the loop took the stop and ended."""

    sent: str
    taken: bool
    ended: bool
    waited_s: float

    @property
    def passed(self) -> bool:
        return self.taken and self.ended

    def lines(self) -> list[str]:
        return [
            f"sent a stop ({self.sent})",
            "the loop took it (inbox_read)"
            if self.taken
            else "the loop never took it: does it read its inbox?",
            "the loop ended as asked" if self.ended else "the loop did not end after taking it",
            *(
                []
                if self.taken
                else ["the stop stays in the inbox: the loop takes it at its next round, whenever that is"]
            ),
            f"{'passed' if self.passed else 'failed'} after {self.waited_s:.0f} s",
        ]


def examine(
    repo: Path,
    loop_id: str,
    timeout_s: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Checkup:
    store.read_manifest(repo, loop_id)  # refuses a loop that is not there before writing anything
    before = len(store.read_events(repo, loop_id)[0])
    entry = store.append_inbox(repo, loop_id, "stop", key=board_key())
    started = clock()
    taken = ended = False
    while True:
        events = store.read_events(repo, loop_id)[0][before:]
        took = next((i for i, e in enumerate(events) if isinstance(e, InboxRead) and entry.id in e.ids), None)
        taken = took is not None
        # Only an end after the loop took this stop counts: a round that stopped for its own reasons
        # while the doctor waited says nothing about whether the loop listens.
        ended = taken and any(
            isinstance(e, LoopStopped) or (isinstance(e, RoundFinished) and e.verdict in ENDING_VERDICTS)
            for e in events[(took or 0) + 1 :]
        )
        waited = clock() - started
        if (taken and ended) or waited >= timeout_s:
            return Checkup(entry.id, taken, taken and ended, waited)
        sleep(POLL_S)
