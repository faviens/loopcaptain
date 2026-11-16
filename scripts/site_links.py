"""Check the links inside the built documentation site, offline: `make links`.

Every `href` and `src` of every page under `site/` that points into the site must lead to a file
that is there, and a `#fragment` to an id on that page. Addresses on other hosts are not opened:
the weekly link workflow does that. A page that includes a file from outside `docs/` (the standard,
the contributing guide) keeps that file's relative links, which lead nowhere on the site; this is
the check that catches them.

    uv run python scripts/site_links.py site
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

LINK_ATTRIBUTES = {"href", "src"}


@dataclass
class Page:
    """What one page links to and which ids it offers as link targets."""

    links: list[str] = field(default_factory=list)
    ids: set[str] = field(default_factory=set)


class PageReader(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.page = Page()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if not value:
                continue
            if name in LINK_ATTRIBUTES:
                self.page.links.append(value)
            if name == "id" or (tag == "a" and name == "name"):
                self.page.ids.add(value)


def read_page(path: Path) -> Page:
    reader = PageReader()
    reader.feed(path.read_text(encoding="utf-8", errors="replace"))
    return reader.page


def target_of(site: Path, page: Path, link: str) -> tuple[Path, str] | None:
    """The file and fragment an internal link names; None for another host, a mail address, a script."""
    parts = urlsplit(link)
    if parts.scheme or parts.netloc:
        return None
    path = unquote(parts.path)
    if not path:
        return page, parts.fragment
    target = (site / path.lstrip("/")) if path.startswith("/") else (page.parent / path)
    target = Path(os.path.normpath(target))
    if target.is_dir():
        target = target / "index.html"
    return target, parts.fragment


def is_file_as_written(site: Path, target: Path) -> bool:
    """True if the file is there under exactly this name: a web server tells `AGENTS` from `agents`,
    the file system of a laptop often does not."""
    if not target.is_file() or not target.is_relative_to(site):
        return False
    folder = site
    for part in target.relative_to(site).parts:
        if part not in {entry.name for entry in folder.iterdir()}:
            return False
        folder = folder / part
    return True


def dead_links(site: Path) -> list[str]:
    """One line per link that leads nowhere: the page, the link, and what is missing."""
    site = site.resolve()
    pages = {path: read_page(path) for path in sorted(site.rglob("*.html"))}
    dead = []
    for path, page in pages.items():
        for link in page.links:
            found = target_of(site, path, link)
            if found is None:
                continue
            target, fragment = found
            name = path.relative_to(site).as_posix()
            if not is_file_as_written(site, target):
                dead.append(f"{name}: {link}: no such file")
            elif fragment and target in pages and unquote(fragment) not in pages[target].ids:
                dead.append(f"{name}: {link}: no such anchor")
    return dead


def main(arguments: list[str]) -> int:
    site = Path(arguments[0]) if arguments else Path("site")
    if not (site / "index.html").is_file():
        sys.stderr.write(f"{site}: no built site here; run `make docs` first\n")
        return 2
    dead = dead_links(site)
    for line in dead:
        sys.stdout.write(f"{line}\n")
    count = len(list(site.rglob("*.html")))
    sys.stdout.write(f"{len(dead)} dead link(s) in {count} page(s)\n")
    return 1 if dead else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
