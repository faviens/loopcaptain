"""What the pages say a figure means and where they lead from it."""

from __future__ import annotations

import itertools
from pathlib import Path

from loopcaptain.board.filters import lead
from loopcaptain.board.overview import main_checkout
from loopcaptain.board.trend import Series, chart

LONG = (
    "The gate failed on two sources. "
    + "Each of the views renders, and the summary table lists every tool. " * 4
)


def test_a_long_summary_reads_its_first_sentence_and_folds_the_rest() -> None:
    head, rest = lead(LONG)

    assert head == "The gate failed on two sources." and rest.startswith("Each of the views")
    assert lead("Short and whole. Two sentences.") == ("Short and whole. Two sentences.", "")


def test_a_measure_counted_towards_a_whole_says_what_is_left() -> None:
    sources = chart(Series("sources_verified", ((1, 100.0), (2, 169.0)), "of 294 sources", better="higher"))
    topics = chart(Series("topics_covered", ((1, 16.0),), "of 16", 16.0, "higher"))
    plain = chart(Series("cost", ((1, 2.0),), "$"))

    assert sources.left == "125 sources left" and sources.series.label == "sources verified"
    assert topics.left == "complete" and plain.left == ""
    assert (topics.tone, sources.tone, plain.tone) == ("good", "good", "plain")


def test_each_round_of_a_chart_has_a_strip_to_point_at() -> None:
    drawn = chart(Series("score", ((1, 0.2), (2, 0.4), (3, 0.9))))

    strips = [(dot.hit_x, dot.hit_x + dot.hit_w) for dot in drawn.dots]
    assert strips[0][0] == 0 and all(a[1] == b[0] for a, b in itertools.pairwise(strips))


def test_a_worktree_is_named_by_the_repository_it_belongs_to(tmp_path: Path) -> None:
    main = tmp_path / "pricing"
    (main / ".git" / "worktrees" / "pricing-loop").mkdir(parents=True)
    worktree = tmp_path / "pricing-loop"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'pricing-loop'}\n")

    assert main_checkout(worktree) == main and main_checkout(main) == main
    assert main_checkout(tmp_path / "nowhere") == tmp_path / "nowhere"


def test_a_chart_short_of_its_target_or_falling_back_reads_amber() -> None:
    short = chart(Series("pass_rate", ((1, 0.5), (2, 0.6)), "", 0.9, "higher"))
    worse = chart(Series("open_findings", ((1, 2.0), (2, 5.0)), better="lower"))

    assert short.met is False and short.tone == "short" and worse.tone == "short"
    assert short.area.endswith("Z") and chart(Series("x", ((1, 1.0),))).area == ""


def test_a_unit_that_only_looks_like_a_whole_does_not_break_the_page() -> None:
    odd = chart(Series("score", ((1, 1.0),), "of ,", better="higher"))

    assert odd.left == ""
