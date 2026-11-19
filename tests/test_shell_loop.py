"""The worked shell loop of the docs runs as printed: it reports, takes a note and a stop, and ends."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from loopcaptain.protocol import signing, store
from loopcaptain.protocol.models import now
from loopcaptain.protocol.state import LoopState, fold
from loopcaptain.protocol.validate import validate_report

ROOT = Path(__file__).resolve().parents[1]
#: An agent that needs two runs: the first leaves a mark, the second finishes the work.
AGENT = "cat >> seen-prompt.txt; if [ -f once ]; then touch finished; fi; touch once; echo worked"


def loop_script() -> str:
    page = (ROOT / "docs" / "shell-loop.md").read_text(encoding="utf-8")
    found = re.search(r"```bash\n(#!/usr/bin/env bash\n# loop\.sh.*?)```", page, re.DOTALL)
    assert found is not None
    return found.group(1)


def run(repo: Path, *, agent: str = AGENT) -> None:
    # `loopcaptain` as this checkout has it, whatever else of that name is installed on the machine.
    shim = repo.parent / "bin"
    shim.mkdir(exist_ok=True)
    source = ROOT / "src"
    (shim / "loopcaptain").write_text(
        f'#!/bin/sh\nPYTHONPATH="{source}" exec "{sys.executable}" -m loopcaptain.cli "$@"\n'
    )
    (shim / "loopcaptain").chmod(0o755)
    env = {
        # Without a file a non-interactive bash reads first: on some machines it puts another PATH first.
        **{name: value for name, value in os.environ.items() if name not in ("BASH_ENV", "ENV")},
        "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}",
        "AGENT_CMD": agent,
        "CHECK_CMD": "test -f finished",
        "MAX_ROUNDS": "3",
    }
    subprocess.run(["bash", "loop.sh"], cwd=repo, env=env, check=True, timeout=120)


def state_of(repo: Path) -> LoopState:
    events, problems = store.read_events(repo, "ralph")
    assert problems == []
    return fold(store.read_manifest(repo, "ralph"), events, store.read_inbox(repo, "ralph")[0], now())


def shell_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "shell"
    repo.mkdir(parents=True)
    (repo / "loop.sh").write_text(loop_script(), encoding="utf-8")
    (repo / "PROMPT.md").write_text("Make the check pass.\n", encoding="utf-8")
    return repo


def test_the_shell_loop_of_the_docs_reports_its_rounds_and_ends_done(tmp_path: Path) -> None:
    repo = shell_repo(tmp_path)

    run(repo)

    state = state_of(repo)
    assert [round_.verdict for round_ in state.rounds] == ["continue", "done"] and state.status == "done"
    assert validate_report(repo).problems == []
    assert (repo / "out" / "round-2.md").read_text(encoding="utf-8") == "worked\n"


def test_the_shell_loop_hands_a_note_to_the_agent_and_takes_a_stop(tmp_path: Path) -> None:
    repo = shell_repo(tmp_path)
    run(repo, agent="cat > seen-prompt.txt; echo tried")  # never done: it stops at its cap
    assert state_of(repo).status != "done"
    keys = signing.board_keys()
    store.append_inbox(repo, "ralph", "stop", keys=keys)
    run(repo)
    stopped = state_of(repo)

    fresh = shell_repo(tmp_path / "second")
    (fresh / ".loops" / "ralph").mkdir(parents=True)
    (fresh / ".loops" / "ralph" / "loop.json").write_text('{"protocol": 1, "id": "ralph"}', encoding="utf-8")
    store.append_inbox(fresh, "ralph", "reply", "Leave the migration alone.", keys=keys)
    run(fresh)

    assert stopped.ended is not None and stopped.ended.stop_reason == "person"
    assert "From the person:\nLeave the migration alone." in (fresh / "seen-prompt.txt").read_text(
        encoding="utf-8"
    )
