"""Reading and writing a loop's folder, `.loops/<loop-id>/` in its repository.

The files are the truth; nothing here keeps state. A line the models refuse is reported, never
fatal: a loop that writes one bad line must not blank its own page.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from loopcaptain.protocol.models import (
    EVENT,
    EVENTS_FILE,
    FOLDER,
    INBOX_FILE,
    MANIFEST_FILE,
    AnyEvent,
    FindingRef,
    InboxEntry,
    InboxKind,
    InboxRead,
    Manifest,
    is_slug,
    now,
)
from loopcaptain.protocol.signing import sign
from loopcaptain.protocol.state import STALE_AFTER

#: The most the board reads of one file. A summary log of a long loop is a few hundred kilobytes.
MAX_LOG_BYTES = 20_000_000
MAX_MANIFEST_BYTES = 1_000_000


class StoreError(Exception):
    """A loop folder that cannot be read or written as asked."""


@dataclass(frozen=True)
class Problem:
    """One thing in a loop's folder the board could not read."""

    file: str
    line: int  # 0 for the whole file
    message: str

    def __str__(self) -> str:
        where = f"{self.file}:{self.line}" if self.line else self.file
        return f"{where}: {self.message}"


def loop_dir(repo: Path, loop_id: str) -> Path:
    if not is_slug(loop_id):
        raise StoreError(f"{loop_id!r} is not a loop id")
    return repo / FOLDER / loop_id


def speaks_protocol(manifest: Path) -> bool:
    """Whether a loop.json is this protocol's: it carries the `protocol` field.

    Other tools keep their own files in a folder called `.loops/`; those are skipped quietly. A
    loop.json that is not JSON at all counts as a loop: `read_manifest` then says what is wrong
    with it, where skipping it would let a loop with a typing mistake vanish without a word.
    """
    try:
        text = read_bounded(manifest, MAX_MANIFEST_BYTES)
    except (FileNotFoundError, StoreError):
        return False
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return True
    return isinstance(data, dict) and "protocol" in data


def loop_ids(repo: Path) -> list[str]:
    """The loops a repository holds: every sub-folder of `.loops/` whose loop.json speaks the protocol."""
    folder = repo / FOLDER
    if folder.is_symlink() or not folder.is_dir():
        return []  # a `.loops` that is a link could show another repository's loops as this one's
    return sorted(
        child.name
        for child in folder.iterdir()
        if is_slug(child.name) and not child.is_symlink() and speaks_protocol(child / MANIFEST_FILE)
    )


def short_error(error: ValidationError) -> str:
    """A validation error in one line, naming the field."""
    parts = []
    for item in error.errors()[:3]:
        where = ".".join(str(part) for part in item["loc"])
        parts.append(f"{where}: {item['msg']}" if where else item["msg"])
    return "; ".join(parts)


# ---- the manifest ----


def read_manifest(repo: Path, loop_id: str) -> Manifest:
    path = loop_dir(repo, loop_id) / MANIFEST_FILE
    try:
        manifest = Manifest.model_validate_json(read_bounded(path, MAX_MANIFEST_BYTES))
    except FileNotFoundError as error:
        raise StoreError(f"{MANIFEST_FILE}: {error.strerror or error}") from error
    except ValidationError as error:
        raise StoreError(f"{MANIFEST_FILE}: {short_error(error)}") from error
    if manifest.id != loop_id:
        raise StoreError(f"{MANIFEST_FILE}: id {manifest.id!r} does not match its folder {loop_id!r}")
    return manifest


def contained(repo: Path, folder: Path, loop_id: str) -> None:
    """Refuse a loop folder that resolves outside its repository, through a link on the way."""
    if not folder.resolve().is_relative_to(repo.resolve()):
        raise StoreError(f"the folder of {loop_id!r} leads out of {repo.name}")


def write_manifest(repo: Path, manifest: Manifest) -> Path:
    """Write `loop.json` whole or not at all: a reader never sees half a file."""
    folder = loop_dir(repo, manifest.id)
    contained(repo, folder, manifest.id)
    folder.mkdir(parents=True, exist_ok=True)
    contained(repo, folder, manifest.id)
    path = folder / MANIFEST_FILE
    tmp = folder / f"{MANIFEST_FILE}.{secrets.token_hex(4)}.tmp"
    tmp.write_text(manifest.model_dump_json(indent=2, exclude_none=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


# ---- events and inbox: one JSON object per line ----


def append_line(path: Path, payload: str) -> None:
    """One write call on a file opened for append: lines from two writers do not interleave.

    A symbolic link is refused: a repository must not be able to point its inbox at another file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as error:
        raise StoreError(f"{path.name}: cannot be written ({error.strerror or error})") from error
    try:
        os.write(descriptor, (payload + "\n").encode("utf-8"))
    finally:
        os.close(descriptor)


def read_bounded(path: Path, limit: int) -> str:
    """A regular file's text, up to `limit` bytes; anything else, a link too, is refused before it is opened.

    The board reads these files on every request, so a pipe that never ends or a log of gigabytes
    in one repository must not stall or fill it.
    """
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise
    except OSError as error:
        raise StoreError(f"{path.name}: {error.strerror or error}") from error
    if not stat.S_ISREG(info.st_mode):
        raise StoreError(f"{path.name}: not a regular file")
    if info.st_size > limit:
        raise StoreError(
            f"{path.name}: {info.st_size // 1_000_000} MB, over the {limit // 1_000_000} MB the board reads"
        )
    try:
        # Bytes that are not text become a marker, so one bad line is reported and the rest reads.
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError as error:
        raise StoreError(f"{path.name}: {error.strerror or error}") from error


def complete_lines(path: Path) -> list[tuple[int, str]]:
    """The complete lines of a file with their numbers. A last line still being written is left out."""
    try:
        text = read_bounded(path, MAX_LOG_BYTES)
    except FileNotFoundError:
        return []
    whole = text if text.endswith("\n") else text[: text.rfind("\n") + 1]
    # A line ends at "\n" and nowhere else: a text may hold U+2028 or U+0085, which `splitlines` cuts at.
    return [(n, line) for n, line in enumerate(whole.split("\n"), start=1) if line.strip()]


def parse_event(data: dict[str, Any]) -> AnyEvent:
    return EVENT.validate_python(data)


def append_event(repo: Path, loop_id: str, event: AnyEvent) -> None:
    append_line(loop_dir(repo, loop_id) / EVENTS_FILE, event.model_dump_json(exclude_none=True))


def read_events(repo: Path, loop_id: str) -> tuple[list[AnyEvent], list[Problem]]:
    events: list[AnyEvent] = []
    problems: list[Problem] = []
    for number, line in complete_lines(loop_dir(repo, loop_id) / EVENTS_FILE):
        try:
            events.append(EVENT.validate_json(line))
        except ValidationError as error:
            problems.append(Problem(EVENTS_FILE, number, short_error(error)))
    return events, problems


def append_inbox(
    repo: Path,
    loop_id: str,
    kind: InboxKind,
    text: str = "",
    round_: int | None = None,
    key: bytes | None = None,
    question: str | None = None,
    choice: str | None = None,
    finding: FindingRef | None = None,
) -> InboxEntry:
    """What the person sends, signed with `key` when given. The loop's folder must exist: the board
    never creates a loop."""
    folder = loop_dir(repo, loop_id)
    if not (folder / MANIFEST_FILE).is_file():
        raise StoreError(f"no loop {loop_id!r} in {repo.name}")
    contained(repo, folder, loop_id)
    stamp = now()
    entry = InboxEntry(
        id=f"{stamp:%Y%m%dT%H%M%S}-{secrets.token_hex(2)}",
        ts=stamp,
        kind=kind,
        text=text.strip(),
        round=round_,
        question=question,
        choice=choice,
        finding=finding,
        loop=loop_id,
    )
    if key is not None:
        entry = entry.model_copy(update={"sig": sign(entry.body(), key)})
    append_line(folder / INBOX_FILE, entry.model_dump_json(exclude_none=True))
    return entry


def read_inbox(repo: Path, loop_id: str) -> tuple[list[InboxEntry], list[Problem]]:
    entries: list[InboxEntry] = []
    problems: list[Problem] = []
    for number, line in complete_lines(loop_dir(repo, loop_id) / INBOX_FILE):
        try:
            entries.append(InboxEntry.model_validate_json(line))
        except ValidationError as error:
            problems.append(Problem(INBOX_FILE, number, short_error(error)))
    return entries, problems


def take_inbox(repo: Path, loop_id: str) -> list[InboxEntry]:
    """What the person sent that the loop has not taken yet, oldest first; marks it read.

    The loop's side of the inbox: it appends `inbox_read` to the loop's own events.
    """
    events, _ = read_events(repo, loop_id)
    taken = {entry_id for event in events if isinstance(event, InboxRead) for entry_id in event.ids}
    entries, _ = read_inbox(repo, loop_id)
    fresh = [entry for entry in entries if entry.id not in taken]
    if fresh:
        append_event(repo, loop_id, InboxRead(ts=now(), ids=[entry.id for entry in fresh]))
    return fresh


def fingerprint(repo: Path, loop_id: str) -> str:
    """Changes whenever any of the loop's files does, and once more when the loop has written
    nothing for so long that a round under way reads as stalled; the page polls it to know when
    to reload. From file stats alone: the poll comes every few seconds and must not read a loop."""
    parts = []
    written = 0.0
    for name in (MANIFEST_FILE, EVENTS_FILE, INBOX_FILE):
        try:
            stat = (loop_dir(repo, loop_id) / name).stat()
            parts.append(f"{stat.st_mtime_ns}-{stat.st_size}")
            written = stat.st_mtime if name == EVENTS_FILE else written
        except OSError:
            parts.append("0")
    quiet = now().timestamp() - written > STALE_AFTER.total_seconds()
    return ".".join([*parts, "quiet" if quiet else "fresh"])


def dump(data: object) -> str:
    return json.dumps(data, ensure_ascii=False)
