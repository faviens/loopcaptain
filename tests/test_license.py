"""The licence is named the same everywhere, and a built package carries its files."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPDX = "Apache-2.0"


def test_the_package_names_the_licence_and_ships_its_files() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]

    assert project["license"] == SPDX
    assert {"LICENSE", "NOTICE"} <= set(project["license-files"])
    for name in project["license-files"]:
        assert (ROOT / name).is_file(), name


def test_every_place_that_names_the_licence_agrees() -> None:
    assert "Apache License" in (ROOT / "LICENSE").read_text()[:200]
    assert f"license: {SPDX}" in (ROOT / "CITATION.cff").read_text()
    assert "Apache License, Version 2.0" in (ROOT / "NOTICE").read_text()
    assert "## License" in (ROOT / "README.md").read_text()


def test_the_citation_names_where_the_code_and_the_documentation_live() -> None:
    citation = (ROOT / "CITATION.cff").read_text()
    urls = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["urls"]

    assert f'repository-code: "{urls["Repository"]}"' in citation
    assert f'url: "{urls["Documentation"]}"' in citation
