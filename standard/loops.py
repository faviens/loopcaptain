"""Loops protocol 1: say what a loop is, what happened, and read the person's answers."""

import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def folder(loop_id, repo="."):
    path = Path(repo) / ".loops" / loop_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def register(loop_id, manifest, repo="."):
    """Write loop.json. `manifest` holds title, brief, steps and so on; id and protocol are set here."""
    target = folder(loop_id, repo) / "loop.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps({**manifest, "protocol": 1, "id": loop_id}, indent=2) + "\n")
    tmp.replace(target)


def emit(loop_id, event, fields=None, repo=".", at=None):
    """Append one event line, stamped now; `at` (a datetime or text) is when it really happened."""
    if "ts" in (fields or {}) or "event" in (fields or {}):
        raise ValueError("emit sets `ts` and `event` itself; give when it happened as `at`")
    now = time.time()
    line = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int(now % 1 * 1000):03d}Z",
        "event": event,
    }
    stamp = at.isoformat() if isinstance(at, datetime) else at
    line.update({key: value for key, value in {"at": stamp, **(fields or {})}.items() if value is not None})
    with open(folder(loop_id, repo) / "events.jsonl", "a") as log:
        log.write(json.dumps(line) + "\n")


def lines(path):
    """The JSON objects of a file, one per complete line; a line that is not JSON is skipped."""
    found = []
    if path.exists():
        complete = path.read_text(errors="replace").rpartition("\n")[0]
        for line in complete.split("\n"):  # a line ends at "\n" only, whatever else the text holds
            try:
                found.append(json.loads(line))
            except (ValueError, RecursionError):
                continue
    return [entry for entry in found if isinstance(entry, dict)]


def last_round(loop_id, repo="."):
    """The highest round the loop has finished, 0 before the first: a new start counts on from it."""
    events = lines(folder(loop_id, repo) / "events.jsonl")
    rounds = [event.get("round") for event in events if event.get("event") == "round_finished"]
    return max([number for number in rounds if isinstance(number, int)], default=0)


def signed(entry, loop_id):
    """True if the board wrote this entry for this loop, False if not, None where there is no key."""
    key = Path(os.environ.get("LOOPCAPTAIN_INBOX_KEY") or "~/.config/loopcaptain/inbox.key").expanduser()
    if not key.is_file():
        return None
    if entry.get("loop") != loop_id:
        return False
    body = {key: value for key, value in entry.items() if key != "sig"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    try:
        secret = bytes.fromhex(key.read_text().strip())
    except ValueError:
        return None  # a key the board would not use either: nothing can be told apart
    mark = hmac.new(secret, text.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(mark, str(entry.get("sig", "")))


def moment(stamp):
    """A `ts` as seconds to compare, or None where it cannot be read. No zone means UTC."""
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()


def stale(entry, asked):
    """True for a reply written before the question it names was last asked: it answers an earlier asking."""
    then, sent = asked.get(str(entry.get("question"))), moment(entry.get("ts"))
    return then is not None and sent is not None and sent < then


def inbox(loop_id, repo="."):
    """What the person sent since the last call, oldest first, with `signed` and `stale`; marks it read."""
    base = folder(loop_id, repo)
    seen, asked = set(), {}
    for event in lines(base / "events.jsonl"):
        if event.get("event") == "inbox_read":
            seen.update(event.get("ids", []))
        elif event.get("event") == "question" and event.get("id"):
            asked[str(event["id"])] = moment(event.get("ts"))
    fresh = [entry for entry in lines(base / "inbox.jsonl") if entry.get("id") and entry["id"] not in seen]
    if fresh:
        emit(loop_id, "inbox_read", {"ids": [entry["id"] for entry in fresh]}, repo)
    taken = [{**entry, "signed": signed(entry, loop_id), "stale": stale(entry, asked)} for entry in fresh]
    if any(entry["signed"] is None for entry in taken):
        sys.stderr.write("loops: no board key to read, so `signed` is None: these entries are unchecked\n")
    return taken
