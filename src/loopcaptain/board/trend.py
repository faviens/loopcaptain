"""Small charts of a loop's rounds, drawn as SVG on the server: is it converging?

No script and no chart library: the content policy allows neither, and a line of a dozen points
needs neither. Each chart is one series over the rounds, with the loop's target where it gave one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from loopcaptain.protocol.state import LoopState

WIDTH = 320
HEIGHT = 96
PAD = 8
#: Height of the band at the top of a chart where the hovered round's value is read out.
READOUT = 16
#: The board's own count of open material findings, which a loop may also report as a measure.
FINDINGS = "open material findings"
#: A unit that names a whole, "of 294 sources": the measure counts towards it.
OF_A_WHOLE = re.compile(r"^of\s+(\d[\d,]*(?:\.\d+)?)\s*(.*)$")


@dataclass(frozen=True)
class Series:
    name: str
    values: tuple[tuple[int, float], ...]  # (round number, value), rounds without a value left out
    unit: str = ""
    target: float | None = None
    better: str | None = None
    #: What the loop says about the measure, where it said it: a name to read, a sentence on what
    #: it counts, a file that lists what is counted.
    title: str = ""
    about: str = ""
    file: str | None = None

    @property
    def label(self) -> str:
        """The name as a person reads it: the loop's own, else `topics_covered` reads "topics covered"."""
        return self.title or self.name.replace("_", " ").strip()


@dataclass(frozen=True)
class Dot:
    x: float
    y: float
    round: int
    value: float
    #: The strip of the chart that belongs to this round: hovering it reads the round out.
    hit_x: float = 0.0
    hit_w: float = 0.0
    #: The round missed the loop's target, where it gave one and a direction.
    off: bool = False


@dataclass(frozen=True)
class Chart:
    series: Series
    path: str
    dots: tuple[Dot, ...]
    target_y: float | None
    width: int = WIDTH
    height: int = HEIGHT

    @property
    def last(self) -> float:
        return self.series.values[-1][1]

    @property
    def first(self) -> float:
        return self.series.values[0][1]

    @property
    def improving(self) -> bool | None:
        """Whether the last value is better than the first, where "better" is known."""
        if self.series.better is None or len(self.series.values) < 2 or self.last == self.first:
            return None
        return (self.last < self.first) if self.series.better == "lower" else (self.last > self.first)

    @property
    def met(self) -> bool | None:
        """Whether the last value reaches the loop's target, where it gave one and a direction."""
        target, better = self.series.target, self.series.better
        if target is None or better is None:
            return None
        return self.last <= target if better == "lower" else self.last >= target

    @property
    def tone(self) -> str:
        """How the chart reads at a glance: `good` on target or getting better, `short` getting
        worse or with work left, `plain` where the loop names no direction (cost, say)."""
        if self.met is True:
            return "good"
        if self.improving is False:
            return "short"
        if self.improving is True:
            return "good" if self.met is None else "short"
        return "short" if self.met is False else "plain"

    @property
    def area(self) -> str:
        """The line closed down to the foot of the chart, for a soft fill under it."""
        if len(self.dots) < 2:
            return ""
        foot = self.height - 1
        return f"{self.path} L{self.dots[-1].x} {foot} L{self.dots[0].x} {foot} Z"

    @property
    def left(self) -> str:
        """What is still to do for a measure counted towards a whole ("of 294 sources"), else ""."""
        whole = OF_A_WHOLE.match(self.series.unit)
        if not whole or self.series.better == "lower":
            return ""
        rest = float(whole[1].replace(",", "")) - self.last
        if rest <= 0:
            return "complete"
        noun = whole[2] or ""
        return f"{figure(rest)} {noun} left".replace("  ", " ")


def series_of(state: LoopState) -> list[Series]:
    """What is worth a line: open material findings, cost (or tokens without a price), every metric."""
    finished = [r for r in state.rounds if not r.running]
    found: list[Series] = []
    reported = {metric.name.replace("_", " ").strip().lower() for r in finished for metric in r.all_metrics}
    if FINDINGS not in reported and any(run.findings for r in finished for run in r.runs):
        found.append(
            Series(
                FINDINGS,
                tuple((r.number, float(sum(run.material_open for run in r.runs))) for r in finished),
                better="lower",
            )
        )
    if any(r.cost_usd for r in finished):
        found.append(Series("cost", tuple((r.number, r.cost_usd) for r in finished), unit="$"))
    elif any(r.tokens for r in finished):
        found.append(Series("tokens", tuple((r.number, float(r.tokens)) for r in finished)))
    names: list[str] = []
    for r in finished:
        names += [metric.name for metric in r.all_metrics if metric.name not in names]
    for name in names:
        points = [(r.number, m) for r in finished for m in r.all_metrics if m.name == name]
        last = points[-1][1]
        found.append(
            Series(
                name,
                tuple((n, m.value) for n, m in points),
                last.unit,
                last.target,
                last.better,
                title=last.label,
                about=last.about,
                file=last.file,
            )
        )
    return [series for series in found if series.values]


def misses(series: Series, value: float) -> bool:
    """Whether one round's value falls short of the loop's target."""
    if series.target is None or series.better is None:
        return False
    return value > series.target if series.better == "lower" else value < series.target


def chart(series: Series, width: int = WIDTH, height: int = HEIGHT) -> Chart:
    values = [value for _, value in series.values]
    low = min([*values, *([series.target] if series.target is not None else [])])
    high = max([*values, *([series.target] if series.target is not None else [])])
    span = (high - low) or 1.0
    count = len(series.values)

    def x(index: int) -> float:
        return PAD + (width - 2 * PAD) * (index / (count - 1) if count > 1 else 0.5)

    def y(value: float) -> float:
        return round(height - PAD - (height - 2 * PAD - READOUT) * (value - low) / span, 1)

    step = (width - 2 * PAD) / (count - 1) if count > 1 else width
    dots = tuple(
        Dot(
            round(x(i), 1),
            y(value),
            number,
            value,
            hit_x=round(max(0.0, x(i) - step / 2), 1),
            hit_w=round(min(float(width), x(i) + step / 2) - max(0.0, x(i) - step / 2), 1),
            off=misses(series, value),
        )
        for i, (number, value) in enumerate(series.values)
    )
    path = " ".join(f"{'M' if i == 0 else 'L'}{dot.x} {dot.y}" for i, dot in enumerate(dots))
    target_y = y(series.target) if series.target is not None else None
    return Chart(series, path, dots, target_y, width, height)


#: A trend draws the latest rounds: a dot per round of a loop of thousands is a page of megabytes.
CHART_ROUNDS = 200


def charts_of(state: LoopState) -> list[Chart]:
    return [chart(replace(series, values=series.values[-CHART_ROUNDS:])) for series in series_of(state)]


#: From this share of a cap on, its bar warns.
WARN_SHARE = 0.8


@dataclass(frozen=True)
class CapBar:
    name: str
    used: str
    cap: str
    share: float  # 0..1, clipped

    @property
    def warns(self) -> bool:
        return self.share >= WARN_SHARE


def caps_of(state: LoopState) -> list[CapBar]:
    """Rounds, this start's rounds, runtime and cost against the loop's own caps, for those it declares."""
    manifest = state.manifest
    bars = []
    if manifest.round_cap:
        used = state.rounds[-1].number if state.rounds else 0
        bars.append(CapBar("rounds", str(used), str(manifest.round_cap), min(1.0, used / manifest.round_cap)))
    start = state.start
    if start is not None and start.budget:
        used = len(start.begun)
        bars.append(
            CapBar(
                f"start {start.number}, rounds", str(used), str(start.budget), min(1.0, used / start.budget)
            )
        )
    if manifest.runtime_cap_minutes:
        share = state.minutes / manifest.runtime_cap_minutes
        bars.append(
            CapBar("runtime", f"{state.minutes} min", f"{manifest.runtime_cap_minutes} min", min(1.0, share))
        )
    if manifest.cost_cap_usd:
        share = state.cost_usd / manifest.cost_cap_usd
        bars.append(
            CapBar("cost", f"${state.cost_usd:,.2f}", f"${manifest.cost_cap_usd:,.2f}", min(1.0, share))
        )
    return bars


#: How many of a loop's latest rounds the overview draws beside its count.
TRAIL_ROUNDS = 12
#: The darkest shade stands for this many open findings or more.
HEAT_LEVELS = 4


@dataclass(frozen=True)
class TrailCell:
    """One round on the overview: `live` while it runs, `clear` with nothing open, else `h1` to `h4`."""

    number: int
    look: str
    label: str


def trail_of(state: LoopState) -> list[TrailCell]:
    """The loop's latest rounds, oldest first, each shaded by the findings it left open."""
    cells = []
    for round_ in state.rounds[-TRAIL_ROUNDS:]:
        left_open = round_.findings_open
        if round_.running:
            look, what = "live", "under way"
        elif left_open == 0:
            look, what = "clear", "nothing open"
        else:
            look = f"h{min(left_open, HEAT_LEVELS)}"
            what = f"{left_open} open finding{'s' if left_open != 1 else ''}"
        cells.append(TrailCell(round_.number, look, f"round {round_.number}: {what}"))
    return cells


def figure(value: float, unit: str = "") -> str:
    """A value as a person reads it: whole numbers without decimals, money with two."""
    if unit == "$":
        return f"${value:,.2f}"
    text = f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
    return f"{text} {unit}".strip()
