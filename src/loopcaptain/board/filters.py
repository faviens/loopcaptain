"""How numbers, times and places read on a page: the template filters."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from loopcaptain.protocol.models import now


def ago(value: datetime | None, at: datetime | None = None) -> str:
    if value is None:
        return ""
    seconds = int(((at or now()) - value).total_seconds())
    if seconds < 60:
        return "just now"
    for size, unit in ((86400, "d"), (3600, "h"), (60, "min")):
        if seconds >= size:
            return f"{seconds // size} {unit} ago"
    return ""


def usd(value: float) -> str:
    return f"${value:,.2f}" if value else ""


def minutes(value: int | None) -> str:
    if not value:
        return ""
    return f"{value} min" if value < 120 else f"{value / 60:.1f} h"


def tokens(value: int) -> str:
    if not value:
        return ""
    return f"{value / 1_000_000:.1f}M" if value >= 1_000_000 else f"{value / 1000:.0f}k"


def stamp(value: datetime | None) -> str:
    if value is None:
        return ""
    try:
        local = value.astimezone()
        # The year is padded by hand: strftime leaves years before 1000 unpadded on some C libraries.
        return f"{local.year:04d}-{local:%m-%d %H:%M}"
    except (OverflowError, ValueError, OSError):
        # A time at the edge of the calendar has no local form: show it as the loop wrote it.
        return f"{value.isoformat(sep=' ', timespec='minutes')}"


def place(path: Path) -> str:
    """Where a repository is, as the person would type it: the home folder as `~`."""
    try:
        return f"~/{path.resolve().relative_to(Path.home())}"
    except ValueError:
        return str(path)


#: A summary shorter than this reads in one go and is not split.
LEAD_CHARS = 220
#: The end of a sentence: a full stop, question or exclamation mark before a space and a capital.
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")


def lead(text: str) -> tuple[str, str]:
    """A step's summary as its first sentence and the rest, so a round reads at a glance.

    A short summary, or one whose first sentence is most of it, stays whole: ("all of it", "").
    """
    text = text.strip()
    if len(text) <= LEAD_CHARS:
        return text, ""
    parts = SENTENCE_END.split(text, maxsplit=1)
    if len(parts) < 2 or len(parts[0]) > len(text) * 3 // 4:
        return text, ""
    return parts[0], parts[1]
