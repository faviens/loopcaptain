"""The picture of one round: the manifest's steps laid out left to right, as numbers a template draws.

No drawing library: each step gets a column (one further right than the last step it waits for)
and a row within it, and every edge is one curve.
"""

from __future__ import annotations

from dataclasses import dataclass

from loopcaptain.protocol.models import Manifest
from loopcaptain.protocol.state import RoundState

NODE_W = 148
NODE_H = 46
GAP_X = 44
GAP_Y = 14
PAD = 14
#: Room under the nodes for the arrow that leads from the last step back to the first.
RETURN_H = 34


@dataclass(frozen=True)
class Node:
    id: str
    name: str
    kind: str
    x: int
    y: int
    #: pending, running, ok, failed, skipped: the step in the round the picture shows.
    state: str = "pending"
    runs: int = 0
    findings: int = 0

    @property
    def cx(self) -> int:
        return self.x + NODE_W // 2

    @property
    def cy(self) -> int:
        return self.y + NODE_H // 2


@dataclass(frozen=True)
class Graph:
    nodes: tuple[Node, ...]
    edges: tuple[str, ...]  # SVG path data
    back: str  # the path from the last column back to the first, "" for a single column
    width: int
    height: int
    node_w: int = NODE_W
    node_h: int = NODE_H


def columns(manifest: Manifest) -> dict[str, int]:
    """Each step's column: 0 for a step that waits for nothing, else one past its latest predecessor.

    In waves, without recursion: a loop.json with thousands of chained steps must not exhaust the
    stack. A step left over after as many waves as there are steps sits in a cycle and goes to 0.
    """
    before: dict[str, list[str]] = {step.id: [] for step in manifest.steps}
    for source, target in manifest.edges():
        before[target].append(source)
    column: dict[str, int] = {}
    for _ in range(len(before)):
        ready = [
            step_id
            for step_id, sources in before.items()
            if step_id not in column and all(name in column for name in sources)
        ]
        if not ready:
            break
        for step_id in ready:
            column[step_id] = 1 + max((column[name] for name in before[step_id]), default=-1)
    return {step_id: column.get(step_id, 0) for step_id in before}


def step_state(round_: RoundState | None, step_id: str) -> tuple[str, int, int]:
    """How a step stands in a round: its state, how many runs it had, how many open material findings."""
    runs = round_.runs_of(step_id) if round_ else ()
    if not runs:
        return "pending", 0, 0
    findings = sum(run.material_open for run in runs)
    statuses = {run.status for run in runs}
    for state in ("running", "failed", "ok"):
        if state in statuses:
            return state, len(runs), findings
    return "skipped", len(runs), findings


def layout(manifest: Manifest, round_: RoundState | None = None) -> Graph:
    column = columns(manifest)
    by_column: dict[int, list[str]] = {}
    for step in manifest.steps:
        by_column.setdefault(column[step.id], []).append(step.id)
    tallest = max((len(ids) for ids in by_column.values()), default=1)
    inner_h = tallest * NODE_H + (tallest - 1) * GAP_Y

    nodes: dict[str, Node] = {}
    for col, ids in by_column.items():
        block = len(ids) * NODE_H + (len(ids) - 1) * GAP_Y
        top = PAD + (inner_h - block) // 2
        for row, step_id in enumerate(ids):
            declared = manifest.step(step_id)
            state, runs, findings = step_state(round_, step_id)
            nodes[step_id] = Node(
                id=step_id,
                name=(declared.name if declared else "") or step_id,
                kind=declared.kind if declared else "other",
                x=PAD + col * (NODE_W + GAP_X),
                y=top + row * (NODE_H + GAP_Y),
                state=state,
                runs=runs,
                findings=findings,
            )

    edges = tuple(curve(nodes[source], nodes[target]) for source, target in manifest.edges())
    last_col = max(by_column, default=0)
    width = 2 * PAD + (last_col + 1) * NODE_W + last_col * GAP_X
    height = 2 * PAD + inner_h
    back = ""
    if last_col > 0:
        floor = height + RETURN_H - 12
        start_x = PAD + last_col * (NODE_W + GAP_X) + NODE_W // 2
        end_x = PAD + NODE_W // 2
        low = PAD + inner_h
        back = (
            f"M {start_x} {low + 4} V {floor - 10} Q {start_x} {floor} {start_x - 10} {floor} "
            f"H {end_x + 10} Q {end_x} {floor} {end_x} {floor - 10} V {low + 8}"
        )
        height += RETURN_H
    return Graph(tuple(nodes.values()), edges, back, width, height)


def curve(source: Node, target: Node) -> str:
    x1, y1 = source.x + NODE_W, source.cy
    x2, y2 = target.x, target.cy
    mid = (x1 + x2) // 2
    return f"M {x1} {y1} C {mid} {y1}, {mid} {y2}, {x2 - 5} {y2}"
