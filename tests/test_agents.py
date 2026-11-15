"""Every agent's MCP line comes from one place, and nothing else in the repository favours a vendor."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from loopcaptain.agents import agents, checkout_of, markdown, server_argv

ROOT = Path(__file__).resolve().parents[1]
#: The files allowed to name an agent's own command: the one source, its page, the
#: attribution guard, the history, and the workflows that explain that guard.
ALLOWED = (
    "src/loopcaptain/agents.py",
    "docs/agents.md",
    ".pre-commit-config.yaml",
    ".github/",
    "CHANGELOG.md",
    "tests/test_agents.py",
)
VENDOR_COMMAND = re.compile(
    r"\b(claude|codex|gemini|amp|copilot|opencode|cursor-agent) (mcp add|-p|exec|-x|run)\b"
)


def test_the_agents_page_is_current() -> None:
    assert (ROOT / "docs" / "agents.md").read_text() == markdown(), "run make docs-pages"


def test_every_agent_has_a_way_in_and_a_way_to_run_unattended() -> None:
    for item in agents("/x"):
        assert item.add and item.headless and item.reads, item.key


def test_no_committed_file_outside_the_agents_page_names_a_vendor_command() -> None:
    listed = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    found = []
    for name in listed.stdout.splitlines():
        if (
            name.startswith(ALLOWED)
            or not (ROOT / name).is_file()
            or name.endswith((".woff2", ".webp", ".png"))
        ):
            continue
        text = (ROOT / name).read_text(encoding="utf-8", errors="ignore")
        found += [f"{name}: {match.group(0)}" for match in VENDOR_COMMAND.finditer(text)]
    assert found == []


def test_the_readme_and_the_board_show_the_prompts_as_standard_prompts_holds_them() -> None:
    readme = (ROOT / "README.md").read_text()
    for name in ("build-a-loop", "watch-my-loops"):
        assert (ROOT / "standard" / "prompts" / f"{name}.md").read_text() in readme, name


def test_an_installed_package_names_the_plain_server_command(tmp_path: Path) -> None:
    assert server_argv(checkout_of(tmp_path)) == ["loopcaptain", "mcp"]
    assert server_argv(checkout_of(ROOT))[:3] == ["uv", "run", "--project"]
