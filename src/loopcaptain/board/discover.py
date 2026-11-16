"""Which loops the board shows: the repositories named in the config, read fresh on every request.

Every repository and every loop is a boundary: a folder the board may not enter, or a loop whose
files cannot be read or folded, is named with the reason and left out, and the rest is shown.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from loopcaptain.protocol import store
from loopcaptain.protocol.models import FOLDER, Manifest, now
from loopcaptain.protocol.signing import untrusted_ids
from loopcaptain.protocol.state import LoopState, fold
from loopcaptain.protocol.store import Problem, StoreError

log = logging.getLogger("loopcaptain.discover")

#: Where the config is looked for, first hit wins. The file names this laptop's folders, so it is
#: never committed (`*.local.yaml` is ignored).
CONFIG_ENV = "LOOPCAPTAIN_CONFIG"
CONFIG_NAMES = ("loopcaptain.local.yaml",)
USER_CONFIG = Path("~/.config/loopcaptain/config.yaml")
GIT_TIMEOUT_S = 3
DEMO_FOLDER = "demo"


@dataclass(frozen=True)
class Config:
    """`roots`: folders whose direct sub-folders are repositories. `repos`: single repositories."""

    roots: tuple[Path, ...] = ()
    repos: tuple[Path, ...] = ()
    source: Path | None = None


@dataclass(frozen=True)
class Repo:
    key: str  # unique on the board, the folder name unless two repositories share it
    path: Path  # of worktrees of one repository, the one whose `.loops` was written last
    others: tuple[Path, ...] = ()  # the other worktrees of the same repository that have `.loops`


def git_common_dir(path: Path) -> Path:
    """The `.git` folder a checkout shares with its worktrees, read from disk without running git.

    A worktree's `.git` is a file, `gitdir: <common>/worktrees/<name>`; a main checkout's is the folder
    itself. The file is only a claim, written inside the watched folder: it counts when the
    repository it names lists this folder back, in `<common>/worktrees/<name>/gitdir`. Anything
    else (no git, an unreadable file, a claim that is not returned) stands for itself, so one
    folder cannot put itself in another repository's place on the board.
    """
    dot_git = path / ".git"
    if dot_git.is_dir():
        return dot_git.resolve()
    try:
        first = dot_git.read_text(encoding="utf-8").splitlines()[0]
        if not first.startswith("gitdir:"):
            return path.resolve()
        gitdir = (path / first.removeprefix("gitdir:").strip()).resolve()
        back = (gitdir / "gitdir").read_text(encoding="utf-8").strip()
        returned = gitdir.parent.name == "worktrees" and (gitdir / back).resolve() == dot_git.resolve()
    except (OSError, IndexError, UnicodeDecodeError, ValueError):
        return path.resolve()
    return gitdir.parent.parent if returned else path.resolve()


def last_written(path: Path) -> int:
    """When anything in a repository's `.loops` was last written, in nanoseconds; 0 if never."""
    folder = path / FOLDER
    stamps = [0]
    for loop_id in store.loop_ids(path):
        for name in ("loop.json", "events.jsonl", "inbox.jsonl"):
            try:
                stamps.append((folder / loop_id / name).lstat().st_mtime_ns)
            except OSError:
                continue
    return max(stamps)


def one_per_repository(paths: list[Path]) -> list[tuple[Path, tuple[Path, ...]]]:
    """Worktrees of one repository become one entry: the last written, and the others beside it."""
    groups: dict[Path, list[Path]] = {}
    for path in paths:
        groups.setdefault(git_common_dir(path), []).append(path)
    grouped = []
    for members in groups.values():
        ordered = sorted(members, key=last_written, reverse=True)
        grouped.append((ordered[0], tuple(ordered[1:])))
    return grouped


@dataclass(frozen=True)
class LoopView:
    """One loop as the board shows it: where it lives, where it stands, and what could not be read."""

    repo: Repo
    loop_id: str
    state: LoopState | None
    problems: tuple[Problem, ...] = ()
    error: str = ""

    @property
    def title(self) -> str:
        return (self.state.manifest.title if self.state else "") or self.loop_id


def load_config(cwd: Path | None = None) -> Config:
    base = cwd or Path.cwd()
    candidates = [Path(os.environ[CONFIG_ENV])] if os.environ.get(CONFIG_ENV) else []
    candidates += [base / name for name in CONFIG_NAMES]
    candidates.append(USER_CONFIG.expanduser())
    for path in candidates:
        if path.is_file():
            return parse_config(path)
    # No config yet: show the example loop if `make demo` has written it, so a fresh clone shows something.
    demo = base / DEMO_FOLDER
    return Config(repos=(demo.resolve(),) if demo.is_dir() else ())


def parse_config(path: Path) -> Config:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, RecursionError, yaml.YAMLError) as error:
        # ValueError: bytes that are not UTF-8 text. RecursionError: nesting deeper than the parser goes.
        raise StoreError(f"{path.name}: {error}") from error
    if not isinstance(data, dict):
        raise StoreError(f"{path.name}: expected `roots:` and `repos:` lists")

    def paths(key: str) -> tuple[Path, ...]:
        value = data.get(key) or []
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise StoreError(f"{path.name}: `{key}` must be a list of paths")
        try:
            return tuple((path.parent / Path(item).expanduser()).resolve() for item in value)
        except (OSError, ValueError) as error:
            # ValueError: a path with a null character, which no file system takes.
            raise StoreError(f"{path.name}: `{key}`: {error}") from error

    return Config(roots=paths("roots"), repos=paths("repos"), source=path)


@dataclass(frozen=True)
class Unreadable:
    """A folder the config names, or one under a `roots:` folder, that the board could not look into."""

    path: Path
    message: str


def reason(error: BaseException) -> str:
    """Why something could not be read, in a few words: the system's own text for a file error."""
    if isinstance(error, OSError) and error.strerror:
        return error.strerror
    return str(error) if isinstance(error, StoreError) else f"{type(error).__name__}: {error}"


def has_loops(path: Path) -> bool:
    """Whether a folder holds a `.loops` folder whose loops can be listed; raises if it cannot be told."""
    if not (path / FOLDER).is_dir():
        return False
    store.loop_ids(path)
    return True


def candidates(config: Config) -> tuple[list[Path], list[Unreadable]]:
    """The folders the config leads to, and those among them the board may not enter."""
    listed: list[Path] = []
    unreadable: list[Unreadable] = []
    for root in config.roots:
        try:
            listed.extend(sorted(root.iterdir()) if root.is_dir() else [])
        except OSError as error:
            unreadable.append(Unreadable(root, reason(error)))
    return list(dict.fromkeys([*listed, *config.repos])), unreadable


def survey(config: Config) -> tuple[list[Path], list[Unreadable]]:
    """Every configured folder with loops the board can list, and every folder it could not look into."""
    listed, unreadable = candidates(config)
    found: list[Path] = []
    for path in listed:
        try:
            if has_loops(path):
                found.append(path)
        except Exception as error:
            # The boundary of one repository: whatever its files make the reader raise, the
            # folder is named with the reason and every other repository is still shown. The
            # page says it on every request, so the log only notes it for debugging.
            log.debug("cannot read %s: %s", path, reason(error))
            unreadable.append(Unreadable(path, reason(error)))
    return found, unreadable


def unreadable_folders(config: Config) -> list[Unreadable]:
    return survey(config)[1]


def find_repos(config: Config) -> list[Repo]:
    """Every configured repository that has a `.loops` folder, each once, in a stable order."""
    found, _ = survey(config)
    grouped = one_per_repository(found)
    names = [path.name for path, _ in grouped]
    repos = []
    for path, others in grouped:
        key = path.name if names.count(path.name) == 1 else f"{path.parent.name}.{path.name}"
        repos.append(Repo(key=safe_key(key), path=path, others=others))
    return repos


def safe_key(name: str) -> str:
    """A repository key is a URL part: anything else in a folder name becomes a dash."""
    return "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in name) or "repo"


def load_loop(repo: Repo, loop_id: str, at: datetime | None = None, process_alive: bool = False) -> LoopView:
    try:
        manifest = store.read_manifest(repo.path, loop_id)
        events, event_problems = store.read_events(repo.path, loop_id)
        inbox, inbox_problems = store.read_inbox(repo.path, loop_id)
        state = fold(manifest, events, inbox, at or now(), process_alive, untrusted_ids(inbox, loop_id))
    except StoreError as error:
        return LoopView(repo, loop_id, None, error=str(error))
    except Exception as error:
        # The boundary of one loop: whatever its files make the reader or the fold raise, this
        # loop shows as unreadable with the reason and every other loop is still shown.
        log.debug("cannot show %s in %s: %s", loop_id, repo.path, reason(error))
        return LoopView(repo, loop_id, None, error=f"cannot be read: {reason(error)}")
    return LoopView(repo, loop_id, state, (*event_problems, *inbox_problems))


def load_all(config: Config) -> list[LoopView]:
    return [load_loop(repo, loop_id) for repo in find_repos(config) for loop_id in store.loop_ids(repo.path)]


def find_repo(config: Config, repo_key: str, loop_id: str) -> Repo | None:
    """The repository behind a URL if it lists this loop, readable or not."""
    return next(
        (
            repo
            for repo in find_repos(config)
            if repo.key == repo_key and loop_id in store.loop_ids(repo.path)
        ),
        None,
    )


def find_loop(config: Config, repo_key: str, loop_id: str) -> tuple[Repo, Manifest] | None:
    """The repository and manifest behind a URL, or None. Only configured repositories are reachable."""
    for repo in find_repos(config):
        if repo.key == repo_key and loop_id in store.loop_ids(repo.path):
            try:
                return repo, store.read_manifest(repo.path, loop_id)
            except Exception as error:
                log.debug("cannot read the manifest of %s in %s: %s", loop_id, repo.path, reason(error))
                return None
    return None


def git_branch(repo: Path) -> str:
    """The checked-out branch, or "" where git cannot say (no repository, detached, too slow)."""
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    branch = done.stdout.strip()
    return branch if done.returncode == 0 and branch != "HEAD" else ""


def config_target() -> Path:
    """The config `watch` and `unwatch` edit: the one `LOOPCAPTAIN_CONFIG` names, else the user's."""
    named = os.environ.get(CONFIG_ENV)
    return Path(named).expanduser() if named else USER_CONFIG.expanduser()


def as_written(path: Path) -> str:
    """A path as it goes into the config: absolute, the home folder as `~`."""
    resolved = path.expanduser().resolve()
    try:
        return f"~/{resolved.relative_to(Path.home())}"
    except ValueError:
        return str(resolved)


def edit_config(path: Path, *, add: tuple[str, str] | None = None, remove: str | None = None) -> list[str]:
    """Add `(key, path)` to the config or remove a path from both lists; returns what changed, in words."""
    target = config_target()
    data: dict[str, list[str]] = {"roots": [], "repos": []}
    if target.is_file():
        loaded = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise StoreError(f"{target}: expected `roots:` and `repos:` lists")
        data.update({key: list(loaded.get(key) or []) for key in ("roots", "repos")})
    changes: list[str] = []
    if add is not None:
        key, entry = add
        if entry in data[key]:
            return [f"{entry} is already under {key}"]
        data[key].append(entry)
        changes.append(f"added {entry} to {key}")
    if remove is not None:
        for key in ("roots", "repos"):
            if remove in data[key]:
                data[key].remove(remove)
                changes.append(f"removed {remove} from {key}")
        if not changes:
            return [f"{remove} is not in {target}"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return [f"{target}: {change}" for change in changes]
