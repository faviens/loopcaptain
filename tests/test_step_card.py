"""The card a step of the graph shows on hover and on keyboard focus: placed inside the picture."""

from __future__ import annotations

import re
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loopcaptain.board.app import create_app
from loopcaptain.board.discover import Config
from loopcaptain.board.graph import layout
from loopcaptain.board.steer import Runner
from loopcaptain.protocol.models import Manifest
from tests.conftest import STEPS

HOST = "board.test"
STYLE = Path(__file__).parent.parent / "src" / "loopcaptain" / "board" / "static" / "style.css"


def manifest_of(steps: list[dict[str, object]]) -> Manifest:
    return Manifest.model_validate({"protocol": 1, "id": "shape", "title": "Shape", "steps": steps})


@pytest.mark.parametrize(
    "steps",
    [
        [{"id": "only", "kind": "build"}],
        [{"id": "a", "kind": "plan"}, {"id": "b", "kind": "build"}],
        STEPS,
        [{"id": f"s{n}", "kind": "build"} for n in range(9)],
    ],
)
def test_every_card_stays_inside_the_picture(steps: list[dict[str, object]]) -> None:
    graph = layout(manifest_of(steps))

    for node in graph.nodes:
        card = graph.card(node)
        assert card.x >= 0 and card.x + card.width <= graph.width, node.id
        assert card.y >= 0 and card.y + card.height <= graph.height, node.id


def test_a_card_stands_beside_its_step_where_there_is_room() -> None:
    graph = layout(manifest_of(STEPS))
    first = graph.nodes[0]

    card = graph.card(first)

    assert card.x >= first.x + graph.node_w


def test_a_step_shows_a_card_with_its_prompt_purpose_and_model_and_keeps_its_title(
    tmp_path: Path, helper: types.ModuleType
) -> None:
    repo = tmp_path / "some-repo"
    repo.mkdir()
    steps = [
        {
            "id": "plan",
            "kind": "plan",
            "purpose": "Decide what this round fixes.",
            "prompt": "prompts/plan.md",
        },
        {"id": "build", "kind": "build", "after": ["plan"], "backend": "an-agent", "model": "a-model"},
    ]
    helper.register("shape", {"title": "Shape", "steps": steps}, repo)
    app = create_app(
        config=lambda: Config(repos=(repo,)), runner=Runner(tmp_path / "s"), allowed_hosts=frozenset({HOST})
    )
    client = TestClient(app, base_url=f"http://{HOST}")
    session = app.state.session
    client.cookies.set(session.cookie_name, session.issue() or "")

    page = client.get("/loop/some-repo/shape").text

    cards = re.findall(r'<foreignObject class="peek[^"]*".*?</foreignObject>', page, re.S)
    assert len(cards) == 2
    assert "Decide what this round fixes." in cards[0] and "prompts/plan.md" in cards[0]
    assert "an-agent" in cards[1] and "a-model" in cards[1]
    assert page.count("<title>") >= 3  # the page's own and one per step, for a screen reader
    assert re.search(r'<a class="hit"[^>]*href="[^"]*path=prompts(/|%2F)plan.md"', page)
    assert re.search(r'<g class="hit"[^>]*tabindex="0"', page)  # a step without a prompt takes focus too
    assert " style=" not in page


def test_the_card_shows_on_hover_and_on_keyboard_focus_and_only_then() -> None:
    style = STYLE.read_text(encoding="utf-8")

    assert re.search(r"svg\.round \.peek \{[^}]*display: none", style)
    shown = re.search(r"([^{}]*)\{ display: block; \}\s*/\* the step card", style)
    assert shown is not None
    assert ".hit:hover .peek" in shown.group(1) and ".hit:focus-visible .peek" in shown.group(1)
