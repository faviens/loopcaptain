"""The first page: loops grouped by repository, and the filters over them."""

from __future__ import annotations

from dataclasses import dataclass

from loopcaptain.board.discover import LoopView, Repo, git_branch
from loopcaptain.board.filters import place


@dataclass(frozen=True)
class Project:
    """One repository on the first page, with the loops that live in it."""

    repo: Repo
    place: str
    branch: str
    views: tuple[LoopView, ...]

    @property
    def waiting(self) -> int:
        return sum(1 for view in self.views if view.state and view.state.question)


def projects_of(views: list[LoopView]) -> list[Project]:
    """The loops grouped by repository, a repository where its first loop stands in `views`."""
    grouped: dict[str, list[LoopView]] = {}
    for view in views:
        grouped.setdefault(view.repo.key, []).append(view)
    return [
        Project(found[0].repo, place(found[0].repo.path), git_branch(found[0].repo.path), tuple(found))
        for found in grouped.values()
    ]


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
