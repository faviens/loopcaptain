"""The documentation pages written from the code are current, and the site builds."""

from __future__ import annotations

import importlib.util
import json
import re
import struct
import sys
import tomllib
import types
from pathlib import Path

import pytest

from loopcaptain.protocol.validate import validate_report

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def docs_pages() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("docs_pages", ROOT / "scripts" / "docs_pages.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_generated_pages_are_current(docs_pages: types.ModuleType) -> None:
    stale = [
        str(path.relative_to(ROOT)) for path, text in docs_pages.pages().items() if path.read_text() != text
    ]

    assert stale == [], "run make docs-pages"


def test_every_command_has_its_section(docs_pages: types.ModuleType) -> None:
    page = docs_pages.cli_page()

    for command in ("serve", "validate", "doctor", "watch", "demo", "mcp-config", "emit"):
        assert f"## `{command}`" in page


@pytest.fixture(scope="module")
def readme_assets() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("readme_assets", ROOT / "scripts" / "readme_assets.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PICTURES = (
    "parts_picture",
    "trust_picture",
    "request_picture",
    "entry_picture",
    "steer_picture",
    "keys_picture",
)


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("draw", PICTURES)
def test_the_architecture_pictures_are_current_and_linked(
    readme_assets: types.ModuleType, draw: str, theme: str
) -> None:
    name = draw.removesuffix("_picture")
    drawn = ROOT / "docs" / "assets" / f"{name}-{theme}.svg"

    assert drawn.read_text(encoding="utf-8") == getattr(readme_assets, draw)(theme), "run make readme"
    assert f"assets/{name}-{theme}.svg" in (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")


def test_no_page_mixes_in_a_chart_of_another_style() -> None:
    pages = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]

    assert [page.name for page in pages if "```mermaid" in page.read_text(encoding="utf-8")] == []


def test_the_first_screen_says_what_it_is_in_the_words_people_search() -> None:
    opening = (ROOT / "README.md").read_text(encoding="utf-8").split("## Get started")[0].lower()
    description = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["description"]
    site = tomllib.loads((ROOT / "zensical.toml").read_text())["project"]["site_description"]

    for word in ("open protocol", "agent loop", "dashboard", "monitor", "steer", "human in the loop"):
        assert word in opening, word
    assert description == site and len(description) <= 120


def test_every_picture_a_page_shows_exists() -> None:
    missing = []
    for page in [ROOT / "README.md", ROOT / "SECURITY.md", *sorted((ROOT / "docs").rglob("*.md"))]:
        base = ROOT if page.parent == ROOT else ROOT / "docs"
        prefix = "docs/assets/" if page.parent == ROOT else "assets/"
        for name in re.findall(rf"{prefix}([\w.-]+\.(?:webp|svg))", page.read_text(encoding="utf-8")):
            if not (base / prefix / name).is_file():
                missing.append(f"{page.name}: {name}")

    assert missing == []
    assert "assets/screenshot-connect.webp" in (ROOT / "docs" / "setup.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["entry", "steer", "keys"])
def test_the_security_pages_show_how_a_browser_gets_in_and_steering_reaches_a_loop(name: str) -> None:
    on_the_code_host = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    on_the_site = (ROOT / "docs" / "security.md").read_text(encoding="utf-8")

    assert f'srcset="docs/assets/{name}-dark.svg"' in on_the_code_host
    assert f'srcset="assets/{name}-dark.svg"' in on_the_site


INSTALL_PAGES = ("README.md", "AGENTS.md", "docs/installation.md", "standard/AGENTS.md")


def test_every_page_an_agent_lands_on_installs_the_released_package() -> None:
    for name in INSTALL_PAGES:
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "not on pypi" not in text.lower(), name
        untagged = re.findall(r"install git\+https://\S+?/loopcaptain(?!@v)", text)
        assert untagged == [], name
        assert re.findall(r"loopcaptain@v\d", text) == [], (
            f"{name} names a release that the next one leaves behind"
        )
    for name in INSTALL_PAGES:
        assert re.search(
            r"uv tool install loopcaptain(?![\w@/-])", (ROOT / name).read_text(encoding="utf-8")
        ), name


def readme_excerpt() -> list[str]:
    """The `events.jsonl` lines the README shows first."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    block = readme.split("```json\n", 1)[1].split("```", 1)[0]
    return block.splitlines()


def test_the_lines_the_readme_shows_validate_as_one_round(tmp_path: Path) -> None:
    lines = readme_excerpt()
    steps = [json.loads(line)["step"] for line in lines if '"step"' in line]
    folder = tmp_path / ".loops" / "memo"
    folder.mkdir(parents=True)
    manifest = {"protocol": 1, "id": "memo", "steps": [{"id": step, "kind": "other"} for step in steps]}
    (folder / "loop.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = validate_report(tmp_path)

    assert len(lines) == 6
    assert (report.problems, report.warnings) == ([], [])
    assert json.loads(lines[-1])["verdict"] == "wait"
    gate = next(json.loads(line) for line in lines if '"step": "gate"' in line)
    assert gate["passed"] is False  # the gate says no as a gate does, not as a step that broke


def test_the_readme_shows_what_it_does_and_the_two_prompts_before_any_detail() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    order = [
        "**Loopcaptain is",
        "hero-light.svg",
        "## Get started",
        "### Start a new loop",
        "### Connect a loop",
    ]
    order += [
        "## The board",
        "screenshot-overview.webp",
        "## Setup",
        "uv tool install loopcaptain",
        "```json",
    ]

    assert [readme.index(part) for part in order] == sorted(readme.index(part) for part in order)
    assert "loopcaptain demo" in readme and "loopcaptain serve" in readme


def test_the_readme_badges_say_what_a_user_needs_and_that_it_is_alpha() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    badges = re.findall(r"^\[!\[([^\]]+)\]", readme, re.MULTILINE)
    opening = readme.split("## Get started")[0]

    assert badges == ["CI", "Docs", "PyPI", "Python", "License"]
    assert "Alpha:" in opening and "protocol 1 only grows" in opening


def test_the_helper_is_as_short_as_the_pages_say() -> None:
    helper = (ROOT / "standard" / "loops.py").read_text(encoding="utf-8").splitlines()

    assert len(helper) < 110
    assert "under 110 lines" in (ROOT / "README.md").read_text(encoding="utf-8")


#: What only the documentation site renders: an included file, a tab, a boxed note.
SITE_ONLY = re.compile(r'^(--8<--|=== "|!!! )', re.MULTILINE)


def test_the_readme_sends_a_reader_to_the_site_for_pages_the_code_host_cannot_render() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    urls = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["urls"]
    linked = re.findall(r"\]\((docs/[\w/.-]+\.md)\)", readme)

    broken = [name for name in linked if SITE_ONLY.search((ROOT / name).read_text(encoding="utf-8"))]

    assert linked and broken == []
    assert urls["Documentation"] in readme


@pytest.fixture(scope="module")
def site_links() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("site_links", ROOT / "scripts" / "site_links.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["site_links"] = module  # a dataclass looks its module up by name
    spec.loader.exec_module(module)
    return module


def test_the_link_check_names_a_missing_page_a_missing_anchor_and_a_wrong_case(
    site_links: types.ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "setup").mkdir()
    (tmp_path / "setup" / "index.html").write_text('<h2 id="run">Run</h2><a href="../#top">up</a>')
    (tmp_path / "index.html").write_text(
        '<a href="setup/#run">ok</a> <a href="setup/#gone">anchor</a> <a href="missing/">page</a>'
        '<a href="SETUP/">case</a> <a href="https://example.org/x">elsewhere</a> <a href="#here">self</a>'
        '<a href="mailto:a@example.org">mail</a> <img src="/setup/index.html"> <p id="here"></p>'
    )

    dead = site_links.dead_links(tmp_path)

    assert dead == [
        "index.html: setup/#gone: no such anchor",
        "index.html: missing/: no such file",
        "index.html: SETUP/: no such file",
        "setup/index.html: ../#top: no such anchor",
    ]
    assert site_links.main([str(tmp_path)]) == 1
    assert site_links.main([str(tmp_path / "setup" / "none")]) == 2


def test_a_link_through_the_sites_own_path_is_a_file_of_the_site(
    site_links: types.ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "setup").mkdir()
    (tmp_path / "setup" / "index.html").write_text("")
    (tmp_path / "404.html").write_text('<a href="/thing/setup/">ok</a> <a href="/thing/gone/">dead</a>')
    (tmp_path / "index.html").write_text("")

    assert site_links.dead_links(tmp_path, "/thing/") == ["404.html: /thing/gone/: no such file"]


#: Files a page of the site includes from outside docs/: a relative link in them leads nowhere there.
INCLUDED = ("standard/AGENTS.md", "CONTRIBUTING.md")


def test_a_file_the_site_includes_links_by_full_address_or_within_itself() -> None:
    for name in INCLUDED:
        text = (ROOT / name).read_text(encoding="utf-8")
        inline = re.findall(r"\]\(([^)\s]+)\)", text)
        defined = re.findall(r"^\[[^\]]+\]: (\S+)$", text, re.MULTILINE)
        used = set(re.findall(r"\]\[([^\]]+)\]", text))

        assert [link for link in inline + defined if not link.startswith(("https://", "#"))] == [], name
        assert used == set(re.findall(r"^\[([^\]]+)\]: ", text, re.MULTILINE)), name


def test_every_link_in_llms_txt_is_a_full_address(docs_pages: types.ModuleType) -> None:
    links = re.findall(r"\]\(([^)]+)\)", docs_pages.llms_txt())
    site, files = docs_pages.addresses()

    assert len(links) >= 11
    assert [link for link in links if not link.startswith((site + "/", files + "/"))] == []
    for link in links:
        if link.startswith(files):
            assert (ROOT / link.removeprefix(files + "/")).is_file(), link
        else:
            page = link.removeprefix(site + "/").rstrip("/")
            assert (ROOT / "docs" / f"{page}.md").is_file(), link


@pytest.fixture(scope="module")
def pypi_readme() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("pypi_readme", ROOT / "scripts" / "pypi_readme.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_package_page_gets_a_readme_whose_every_address_is_full_and_at_the_tag(
    pypi_readme: types.ModuleType,
) -> None:
    text = pypi_readme.readme_for("1.2.3")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    files = project["urls"]["Repository"] + "/blob/v1.2.3/"
    pictures = re.findall(r'(?:src|srcset)="([^"]+)"', text)
    links = re.findall(r"\]\(([^)\s]+)\)", text)

    assert len(pictures) >= 12 and all("/v1.2.3/docs/assets/" in picture for picture in pictures)
    assert [link for link in links if not link.startswith("https://")] == []
    assert "/blob/main/" not in text and f"follow {files}AGENTS.md, section A." in text
    for address in [link for link in links if link.startswith(files)] + pictures:
        path = address.split("/v1.2.3/", 1)[1].split("#")[0]
        assert (ROOT / path).is_file(), address


def test_a_build_from_the_branch_keeps_the_branch_and_leaves_other_hosts_alone(
    pypi_readme: types.ModuleType,
) -> None:
    repository = "https://example.org/owner/thing"
    text = '<img src="docs/a.svg"> ![b](docs/b.webp) [c](LICENSE) [d](https://example.com/x) [e](#more)'

    assert pypi_readme.ref_of("0.0.0") == "main" and pypi_readme.ref_of("0.4.0") == "v0.4.0"
    assert pypi_readme.absolute(text, repository, "main") == (
        '<img src="https://raw.githubusercontent.com/owner/thing/main/docs/a.svg"> '
        "![b](https://raw.githubusercontent.com/owner/thing/main/docs/b.webp) "
        "[c](https://example.org/owner/thing/blob/main/LICENSE) [d](https://example.com/x) [e](#more)"
    )


def test_the_build_takes_its_long_description_from_that_script() -> None:
    settings = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert "readme" in settings["project"]["dynamic"] and "readme" not in settings["project"]
    assert (ROOT / settings["tool"]["hatch"]["metadata"]["hooks"]["custom"]["path"]).is_file()


def test_every_variable_the_code_reads_is_on_the_configuration_page() -> None:
    read = set()
    for path in (ROOT / "src").rglob("*.py"):
        read |= set(re.findall(r'"(LOOPCAPTAIN_[A-Z_]+)"', path.read_text(encoding="utf-8")))
    page = (ROOT / "docs" / "reference" / "configuration.md").read_text(encoding="utf-8")

    assert read and [name for name in sorted(read) if f"`{name}`" not in page] == []
    assert not (ROOT / ".env.example").exists(), "nothing reads a .env file: the page lists the variables"


def test_the_site_knows_its_own_address_so_its_sitemap_and_canonical_links_are_filled() -> None:
    site = tomllib.loads((ROOT / "zensical.toml").read_text())["project"]
    documentation = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["urls"]["Documentation"]

    assert site.get("site_url") == documentation


def front_matter(page: Path) -> dict[str, str]:
    """The `key: "value"` lines between a page's opening `---` lines, if it has them."""
    text = page.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    head = text.split("---\n", 2)[1]
    return dict(re.findall(r'^(\w+): "([^"]*)"$', head, re.MULTILINE))


def test_every_written_page_tells_a_search_engine_what_it_is_about_in_its_own_words() -> None:
    written = [page for page in sorted((ROOT / "docs").rglob("*.md")) if page.parent.name != "reference"]
    descriptions = {
        page.name: front_matter(page).get("description", "") for page in written if page.name != "index.md"
    }

    assert front_matter(ROOT / "docs" / "index.md").get("title", "Home") != "Home"
    assert [name for name, text in descriptions.items() if not 40 <= len(text) <= 160] == []
    assert len(set(descriptions.values())) == len(descriptions)


def test_a_shared_link_and_a_search_result_get_a_title_a_sentence_and_a_picture() -> None:
    """The site wrote no card data and loaded its fonts from another host."""
    theme = tomllib.loads((ROOT / "zensical.toml").read_text(encoding="utf-8"))["project"]["theme"]
    head = (ROOT / "overrides" / "main.html").read_text(encoding="utf-8")
    card = (ROOT / "docs" / "assets" / "social-card.png").read_bytes()

    assert theme["custom_dir"] == "overrides" and theme["font"] is False
    for name in ("og:title", "og:description", "og:url", "og:image", "twitter:card", "application/ld+json"):
        assert name in head
    assert "assets/social-card.png" in head and "http" not in head.replace("https://schema.org", "").replace(
        "https://www.apache.org/licenses/LICENSE-2.0", ""
    )
    assert card[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", card[16:24]) == (1200, 630)
