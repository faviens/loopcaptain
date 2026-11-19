"""The first page: loops grouped by repository, and the filters over them."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from loopcaptain.board.discover import LoopView, Repo, git_branch
from loopcaptain.board.filters import place
from loopcaptain.protocol.models import now
from loopcaptain.protocol.state import no_progress_signs


@dataclass(frozen=True)
class Project:
    """One repository on the first page, with the loops that live in it."""

    repo: Repo
    place: str
    branch: str
    views: tuple[LoopView, ...]
    #: The repository's own name: the folder of its main checkout, also when the loop runs in a
    #: worktree of it elsewhere. `worktree` is that worktree's folder, "" for the main checkout.
    name: str = ""
    worktree: str = ""

    @property
    def waiting(self) -> int:
        return sum(1 for view in self.views if view.state and view.state.question)


def main_checkout(folder: Path) -> Path:
    """The main checkout a folder belongs to: itself, or for a worktree the one it was added from.

    Read from the worktree's `.git` file (`gitdir: <main>/.git/worktrees/<name>`), so nothing runs."""
    marker = folder / ".git"
    try:
        if not marker.is_file():
            return folder
        pointer = marker.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return folder
    if not pointer.startswith("gitdir:"):
        return folder
    gitdir = Path(pointer.removeprefix("gitdir:").strip())
    if not gitdir.is_absolute():
        gitdir = (folder / gitdir).resolve()
    if gitdir.parent.name == "worktrees" and gitdir.parent.parent.name == ".git":
        return gitdir.parent.parent.parent
    return folder


def projects_of(views: list[LoopView]) -> list[Project]:
    """The loops grouped by repository, a repository where its first loop stands in `views`."""
    grouped: dict[str, list[LoopView]] = {}
    for view in views:
        grouped.setdefault(view.repo.key, []).append(view)
    projects = []
    for found in grouped.values():
        folder = found[0].repo.path
        main = main_checkout(folder)
        worktree = folder.name if main.name != folder.name else ""
        projects.append(
            Project(found[0].repo, place(folder), git_branch(folder), tuple(found), main.name, worktree)
        )
    return projects


def repeated_ids(pairs: Iterable[tuple[str, str]]) -> dict[str, tuple[str, ...]]:
    """Each loop id more than one watched repository uses, with those repositories' keys in order.

    `pairs` is (repository key, loop id). The board tells such loops apart by folder; the person
    may not, and a loop with an earlier helper takes lines signed with the key every loop shares."""
    where: dict[str, dict[str, None]] = {}
    for repo_key, loop_id in pairs:
        where.setdefault(loop_id, {})[repo_key] = None
    return {loop_id: tuple(repos) for loop_id, repos in where.items() if len(repos) > 1}


#: Statuses that are over; the overview folds them away unless asked.
FINISHED = frozenset({"done", "stopped"})


def filter_views(
    views: list[LoopView], text: str, statuses: frozenset[str], *, show_finished: bool
) -> tuple[list[LoopView], int]:
    """The loops the table shows, and how many finished ones were folded away. No status is every status."""
    needle = text.strip().lower()

    def status_of(view: LoopView) -> str:
        return view.state.status if view.state else "failed"

    def matches(view: LoopView) -> bool:
        haystack = f"{view.title} {view.loop_id} {view.repo.key}".lower()
        if view.state:
            haystack += " " + view.state.manifest.brief.goal.lower()
        return (not needle or needle in haystack) and (not statuses or status_of(view) in statuses)

    picked = [view for view in views if matches(view)]
    if show_finished or statuses & FINISHED:
        return picked, 0
    kept = [view for view in picked if status_of(view) not in FINISHED]
    return kept, len(picked) - len(kept)


#: Statuses that mean a loop has stopped short or broken: the person should look.
TROUBLE = frozenset({"stalled", "failed", "capped"})


def needs_look(view: LoopView) -> bool:
    """A loop the person should look at: stalled, failed or capped, or going round without progress."""
    if view.state is None:
        return True
    status = view.state.status
    if status in TROUBLE:
        return True
    return status not in FINISHED and bool(no_progress_signs(view.state))


#: The groups the first page sorts loops into, each loop into exactly one, in this order of
#: precedence: what waits for the person, what needs a look, what runs, what rests, what is over.
GROUPS = {
    "waiting": "waiting for you",
    "look": "needs a look",
    "running": "running",
    "idle": "idle",
    "finished": "finished",
    "old": "quiet for weeks",
    "hidden": "hidden",
}
#: The groups the first page leaves out until one of them is asked for.
APART = frozenset({"hidden"})
#: A loop that stalled or failed and has written nothing for this long is no alarm any more: it
#: stays listed, marked old, and leaves the count of loops that need a look.
OLD_AFTER = timedelta(days=14)


def is_old(view: LoopView, at: datetime | None = None) -> bool:
    """Whether a loop that stopped short did so long ago: stalled or failed, and silent for weeks."""
    state = view.state
    if state is None or state.status not in ("stalled", "failed") or state.last_event is None:
        return False
    return (at or now()) - state.last_event > OLD_AFTER


def group_of(view: LoopView) -> str:
    """The one group a loop belongs to on the first page."""
    if view.hidden:
        return "hidden"
    if view.state is None:
        return "look"
    if view.state.question:
        return "waiting"
    if is_old(view):
        return "old"
    if needs_look(view):
        return "look"
    if view.state.status in ("running", "sleeping"):
        return "running"
    if view.state.status in FINISHED:
        return "finished"
    return "idle"
