"""The helper and the example loop run on the oldest Python the standard names, not only on the board's."""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from loopcaptain.protocol import spec_text
from loopcaptain.protocol.validate import validate_report
from tests.conftest import helper_source

OLDEST = (3, 9)
EXAMPLE = Path(__file__).resolve().parents[1] / "src" / "loopcaptain" / "demo" / "loop.py"
#: Names the standard library gained after OLDEST, by module. Not every one: those a loop reaches for.
NEWER_NAMES = {
    "datetime": {"UTC"},
    "itertools": {"pairwise", "batched"},
    "enum": {"StrEnum"},
    "types": {"NoneType", "UnionType"},
    "typing": {"Self", "TypeAlias", "ParamSpec", "Never", "assert_never", "override", "NotRequired"},
}
NEWER_MODULES = {"tomllib"}
FIND_TIMEOUT_S = 20
RUN_TIMEOUT_S = 60


def sources() -> dict[str, str]:
    return {
        "the helper in LOOPS.md": helper_source(),
        "the example loop": EXAMPLE.read_text(encoding="utf-8"),
    }


def newer_names(source: str) -> list[str]:
    """What a source uses that OLDEST does not have; parsing fails on syntax newer than OLDEST."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source, feature_version=OLDEST)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names if alias.name in NEWER_MODULES]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            newer = NEWER_NAMES.get(module, set())
            found += [module] if module in NEWER_MODULES else []
            found += [f"{module}.{alias.name}" for alias in node.names if alias.name in newer]
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.attr in NEWER_NAMES.get(node.value.id, set()):
                found.append(f"{node.value.id}.{node.attr}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "zip":
            found += ["zip(strict=)" for keyword in node.keywords if keyword.arg == "strict"]
    return found


def oldest_python() -> str | None:
    """An interpreter of version OLDEST on this machine, or None."""
    version = ".".join(str(part) for part in OLDEST)
    named = shutil.which(f"python{version}")
    if named:
        return named
    uv = shutil.which("uv")
    if uv is None:
        return None
    try:
        found = subprocess.run(
            [uv, "python", "find", "--offline", version],
            capture_output=True,
            text=True,
            timeout=FIND_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return found.stdout.strip() if found.returncode == 0 and found.stdout.strip() else None


def test_the_standard_names_the_oldest_python_these_tests_hold_the_helper_to() -> None:
    claimed = re.search(r"Standard library only, for Python (\d+)\.(\d+) and later", spec_text())

    assert claimed is not None and (int(claimed.group(1)), int(claimed.group(2))) == OLDEST


@pytest.mark.parametrize("name", sorted(sources()))
def test_nothing_in_the_helper_or_the_example_is_newer_than_the_oldest_python(name: str) -> None:
    assert newer_names(sources()[name]) == []


def test_the_static_check_sees_what_an_older_python_lacks() -> None:
    source = "from datetime import UTC, datetime\nimport tomllib\nimport itertools\nitertools.pairwise([])\n"

    assert newer_names(source) == ["datetime.UTC", "tomllib", "itertools.pairwise"]
    with pytest.raises(SyntaxError):
        newer_names("match command:\n    case _:\n        pass\n")


def test_the_example_loop_runs_on_the_oldest_python(tmp_path: Path) -> None:
    python = oldest_python()
    if python is None:
        pytest.skip(f"no Python {OLDEST[0]}.{OLDEST[1]} on this machine")
    (tmp_path / "loops.py").write_text(helper_source(), encoding="utf-8")
    (tmp_path / "loop.py").write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")

    version = subprocess.run([python, "--version"], capture_output=True, text=True, check=True)
    for arguments in (["--seed", "2"], ["--rounds", "1", "--pace", "0", "--wait", "0"]):
        subprocess.run([python, "loop.py", *arguments], cwd=tmp_path, check=True, timeout=RUN_TIMEOUT_S)

    assert f"{OLDEST[0]}.{OLDEST[1]}." in version.stdout + version.stderr
    assert validate_report(tmp_path).problems == []
    assert (tmp_path / "work" / "rounds" / "3-plan.md").is_file()
