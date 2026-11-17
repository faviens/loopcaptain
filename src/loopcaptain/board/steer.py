"""Steering a loop from the board: the inbox, and starting the one command a loop declares.

The board runs nothing a browser typed. `start` runs `commands.start` from the loop's own
`loop.json`, split into arguments and run without a shell, in the repository root, with a
minimal environment: the board's own variables (keys, tokens) do not travel to a command a
watched repository wrote. The first start of a given command in a given repository needs the
person's tick; the hash of what they confirmed is kept in the state folder. That folder is the
person's own (`state_home`), never one inside the folder the board happens to be started in: what
it holds decides which command runs without a tick and which process "End" signals.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loopcaptain.board.discover import Repo, git_common_dir, safe_key
from loopcaptain.protocol.models import Manifest, now
from loopcaptain.protocol.signing import KEY_ENV, key_path
from loopcaptain.protocol.store import StoreError

log = logging.getLogger("loopcaptain.steer")

STATE_ENV = "LOOPCAPTAIN_STATE"
XDG_STATE_ENV = "XDG_STATE_HOME"
STATE_FOLDER = "loopcaptain"
USER_STATE = Path("~/.local/state")
MAX_PID = 2**31
LOG_TAIL_LINES = 30
LOG_TAIL_BYTES = 20_000
#: The only variables a started loop inherits from the board, beside the key's path (`minimal_env`).
PASSED_ENV = ("PATH", "HOME", "LANG", "TERM")
CONFIRMED_FILE = "confirmed.json"
PRIVATE_MODE = 0o600
PRIVATE_FOLDER_MODE = 0o700
#: How far two readings of the boot time may differ and still be the same boot.
BOOT_TOLERANCE_S = 120.0
#: How many hex digits of a repository's digest name its records: enough that two never meet.
DIGEST_CHARS = 16


def boot_time() -> float:
    """When this machine started, in epoch seconds, from the clock that counts since boot.

    A pid recorded before a reboot can belong to another process now; comparing boot times
    tells the two apart without running anything (the board runs nothing but `commands.start`).
    """
    clock = getattr(time, "CLOCK_BOOTTIME", time.CLOCK_MONOTONIC)
    return time.time() - time.clock_gettime(clock)


def state_home() -> Path:
    """Where the board keeps its records: the folder `LOOPCAPTAIN_STATE` names, else the user's own
    state folder (`$XDG_STATE_HOME/loopcaptain`, else `~/.local/state/loopcaptain`)."""
    named = os.environ.get(STATE_ENV)
    if named:
        return Path(named).expanduser()
    base = os.environ.get(XDG_STATE_ENV)
    # The XDG text says a relative path there is to be ignored.
    root = Path(base) if base and Path(base).is_absolute() else USER_STATE.expanduser()
    return root / STATE_FOLDER


def minimal_env() -> dict[str, str]:
    """The environment a started loop gets: enough to find programs and its home, and the path of the
    key the board signs with, whether or not the board's own environment names it."""
    passed = {name: os.environ[name] for name in PASSED_ENV if name in os.environ}
    return {**passed, KEY_ENV: str(key_path())}


def identity(repo: Repo) -> str:
    """What a repository is, for the board's records: the `.git` its worktrees share, else its folder.

    Two repositories of one name in different folders differ; worktrees of one repository, which
    the board shows as one, do not, so a record survives the board reading from another worktree.
    """
    return str(git_common_dir(repo.path))


def command_hash(repo: Repo, command: str) -> str:
    return hashlib.sha256(f"{repo.path.resolve()}\0{command}".encode()).hexdigest()


def write_private(path: Path, text: str) -> None:
    """Write a file only this user can read: the board's state names repositories and commands."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=PRIVATE_FOLDER_MODE)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_MODE)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)


@dataclass(frozen=True)
class Process:
    pid: int
    command: str
    started: datetime
    alive: bool


class Runner:
    """Starts loops and remembers them: in memory while the board runs, in a small file across restarts."""

    def __init__(self, state_dir: Path | None = None) -> None:
        self.state_dir = state_dir or state_home()
        self.children: dict[str, subprocess.Popen[bytes]] = {}

    def name(self, repo: Repo, loop_id: str) -> str:
        """The file name of a loop's record and log: readable, and one per repository and loop."""
        # Both halves follow the identity, not `repo.key`: the key changes with the worktree the
        # board last read, and the record must not.
        shared = Path(identity(repo))
        label = safe_key(shared.parent.name if shared.name == ".git" else shared.name)
        digest = hashlib.sha256(str(shared).encode()).hexdigest()[:DIGEST_CHARS]
        return f"{label}-{digest}~{loop_id}"

    def record_path(self, repo: Repo, loop_id: str) -> Path:
        return self.state_dir / f"{self.name(repo, loop_id)}.json"

    def log_path(self, repo: Repo, loop_id: str) -> Path:
        return self.state_dir / f"{self.name(repo, loop_id)}.log"

    def confirmed_hashes(self) -> frozenset[str]:
        try:
            listed = json.loads((self.state_dir / CONFIRMED_FILE).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return frozenset()
        except (OSError, ValueError) as error:
            log.warning("unreadable %s, every command needs a tick again: %s", CONFIRMED_FILE, error)
            return frozenset()
        return frozenset(str(item) for item in listed) if isinstance(listed, list) else frozenset()

    def is_confirmed(self, repo: Repo, command: str) -> bool:
        """Whether the person has started this exact command in this repository before."""
        return command_hash(repo, command) in self.confirmed_hashes()

    def confirm(self, repo: Repo, command: str) -> None:
        hashes = sorted(self.confirmed_hashes() | {command_hash(repo, command)})
        write_private(self.state_dir / CONFIRMED_FILE, json.dumps(hashes) + "\n")

    def process(self, repo: Repo, loop_id: str) -> Process | None:
        """The process the board last started for this loop, and whether it still runs."""
        try:
            record = json.loads(self.record_path(repo, loop_id).read_text(encoding="utf-8"))
            pid, command = int(record["pid"]), str(record["command"])
            if record.get("repo") != identity(repo):
                # One state folder serves every board of this user: a record made for another
                # repository is not this loop's.
                return None
            started = datetime.fromisoformat(str(record["started"]))
            if not 1 < pid < MAX_PID:
                # 0 and negative numbers name process groups, the board's own among them.
                raise ValueError(f"pid {pid} is not a process the board could have started")
            boot = record.get("boot")
            same_boot = boot is None or abs(float(boot) - boot_time()) < BOOT_TOLERANCE_S
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError) as error:
            log.warning("unreadable process record for %s: %s", self.name(repo, loop_id), error)
            return None
        return Process(pid, command, started, same_boot and self.is_alive(self.name(repo, loop_id), pid))

    def is_alive(self, name: str, pid: int) -> bool:
        child = self.children.get(name)
        if child is not None and child.pid == pid:
            return child.poll() is None
        try:
            os.kill(pid, 0)  # after a board restart: asks only whether the pid exists
        except ProcessLookupError:
            return False
        except PermissionError:
            return False  # the pid now belongs to someone else's process
        return True

    def start(self, repo: Repo, manifest: Manifest) -> Process:
        command = manifest.commands.get("start", "").strip()
        if not command:
            raise StoreError("this loop declares no start command in loop.json")
        current = self.process(repo, manifest.id)
        if current and current.alive:
            raise StoreError(f"already running (pid {current.pid})")
        try:
            argv = shlex.split(command)
        except ValueError as error:
            raise StoreError(f"start command cannot be read: {error}") from error
        if not argv:
            raise StoreError("start command is empty")
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=PRIVATE_FOLDER_MODE)
        started = now()
        descriptor = os.open(
            self.log_path(repo, manifest.id), os.O_WRONLY | os.O_CREAT | os.O_APPEND, PRIVATE_MODE
        )
        with os.fdopen(descriptor, "ab") as out:
            out.write(f"\n$ {command}   ({started:%Y-%m-%d %H:%M} UTC)\n".encode())
            out.flush()
            try:
                child = subprocess.Popen(
                    argv,
                    cwd=repo.path,
                    env=minimal_env(),
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,  # its own group: closing the board does not kill the loop
                )
            except OSError as error:
                raise StoreError(f"could not start {argv[0]!r}: {error.strerror or error}") from error
        name = self.name(repo, manifest.id)
        self.children[name] = child
        record = {
            "pid": child.pid,
            "command": command,
            "started": started.isoformat(),
            "boot": boot_time(),
            "repo": identity(repo),
        }
        write_private(self.record_path(repo, manifest.id), json.dumps(record) + "\n")
        log.info("started %s: %s (pid %d)", name, command, child.pid)
        return Process(child.pid, command, started, True)

    def kill(self, repo: Repo, loop_id: str) -> bool:
        """End the process the board started, and its children, now. The polite way is an inbox `stop`.

        False when no process group of that pid was left to signal: it had ended on its own."""
        current = self.process(repo, loop_id)
        if not current or not current.alive:
            raise StoreError("nothing the board started is running")
        try:
            os.killpg(current.pid, signal.SIGTERM)
        except ProcessLookupError:
            log.info("%s (pid %d) had already ended", self.name(repo, loop_id), current.pid)
            return False
        except PermissionError as error:
            raise StoreError(f"may not end pid {current.pid}") from error
        log.info("ended %s (pid %d)", self.name(repo, loop_id), current.pid)
        return True

    def log_tail(self, repo: Repo, loop_id: str) -> str:
        path = self.log_path(repo, loop_id)
        try:
            with path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - LOG_TAIL_BYTES))
                text = handle.read().decode("utf-8", errors="replace")
        except FileNotFoundError:
            return ""
        except OSError as error:
            log.warning("cannot read %s: %s", path.name, error)
            return ""
        return "\n".join(text.splitlines()[-LOG_TAIL_LINES:])
