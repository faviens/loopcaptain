"""Reading a loop's start command: the arguments it splits into, and whether it shows as it runs.

The person approves a command by reading it on the page. A character that does not show, or that
changes the order in which the others are drawn, makes the text read as another command than the
one that would run, so such a command is marked on the page and never started.
"""

from __future__ import annotations

import shlex
import unicodedata
from dataclasses import dataclass

#: Unicode categories of characters that do not show as themselves: control and format characters
#: (among them the ones that turn the reading direction), line and paragraph separators, private
#: use, lone surrogates. A space other than the plain one reads as a gap between arguments and is
#: none, so it is refused with them.
HIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp", "Co", "Cs"})
OTHER_SPACE = "Zs"


def is_hidden(char: str) -> bool:
    category = unicodedata.category(char)
    return category in HIDDEN_CATEGORIES or (category == OTHER_SPACE and char != " ")


def code_point(char: str) -> str:
    return f"U+{ord(char):04X}"


@dataclass(frozen=True)
class StartCommand:
    """`commands.start` as the board reads it. `problem` is empty when the board would run it."""

    text: str
    argv: tuple[str, ...] = ()
    problem: str = ""

    @property
    def shown(self) -> str:
        """The text with every character that does not show written out as its code point."""
        return "".join(f"<{code_point(char)}>" if is_hidden(char) else char for char in self.text)


def read_command(text: str) -> StartCommand:
    stripped = text.strip()
    if not stripped:
        return StartCommand(stripped, problem="this loop declares no start command in loop.json")
    hidden = sorted({code_point(char) for char in stripped if is_hidden(char)})
    if hidden:
        return StartCommand(
            stripped,
            problem="the start command holds characters that do not show as they run "
            f"({', '.join(hidden)}); the board does not start it",
        )
    try:
        argv = tuple(shlex.split(stripped))
    except ValueError as error:
        return StartCommand(stripped, problem=f"start command cannot be read: {error}")
    if not argv:
        return StartCommand(stripped, problem="start command is empty")
    return StartCommand(stripped, argv)
