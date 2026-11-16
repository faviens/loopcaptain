"""Loops protocol 1: say what a loop is, what happened, and read the person's answers."""

import hashlib
import hmac
import json
import os
import time
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


def emit(loop_id, event, fields=None, repo="."):
    """Append one event line. Fields that are None are left out."""
    now = time.time()
    line = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int(now % 1 * 1000):03d}Z",
        "event": event,
    }
    line.update({key: value for key, value in (fields or {}).items() if value is not None})
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


def inbox(loop_id, repo="."):
    """What the person sent since the last call, oldest first, each with `signed`, and mark it read."""
    base = folder(loop_id, repo)
    seen = set()
    for event in lines(base / "events.jsonl"):
        if event.get("event") == "inbox_read":
            seen.update(event.get("ids", []))
    fresh = [entry for entry in lines(base / "inbox.jsonl") if entry.get("id") and entry["id"] not in seen]
    if fresh:
        emit(loop_id, "inbox_read", {"ids": [entry["id"] for entry in fresh]}, repo)
    return [{**entry, "signed": signed(entry, loop_id)} for entry in fresh]
