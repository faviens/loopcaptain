"""Draw the README's banner, the how-it-works picture and the architecture's parts, light and dark: `make readme`.

Plain SVG in the board's own palette (warm canvas, ink, one iris accent), written to docs/assets/.
No dependency, so the pictures are redrawn the same on any machine.
"""

from __future__ import annotations

import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "docs" / "assets"
FONT = "Inter Tight, Inter, ui-sans-serif, -apple-system, Segoe UI, Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SF Mono, Menlo, monospace"

THEMES: dict[str, dict[str, str]] = {
    "light": {
        "paper": "#F6F5F2",
        "card": "#FFFFFF",
        "sunk": "#EDECE8",
        "ink": "#1D1D1F",
        "grey": "#646469",
        "hair": "#DAD9D5",
        "accent": "#4A3FE0",
        "good": "#13804B",
        "blue": "#0B7296",
        "group": "#ECEAE5",
        "edge": "#CBC8C0",
        "shade": "#1D1D1F",
    },
    "dark": {
        "paper": "#000000",
        "card": "#1C1C1E",
        "sunk": "#111113",
        "ink": "#F5F5F7",
        "grey": "#A1A1A6",
        "hair": "#38383A",
        "accent": "#A8A1FF",
        "good": "#4FBF82",
        "blue": "#5BB8D8",
        "group": "#1C1C1E",
        "edge": "#0A0A0B",
        "shade": "#000000",
    },
}


def text(x: float, y: float, body: str, size: float, fill: str, weight: int = 400, extra: str = "") -> str:
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" {extra}>{body}</text>'
    )


def card(x: float, y: float, w: float, h: float, t: dict[str, str], fill: str = "card") -> str:
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{t[fill]}" stroke="{t["hair"]}" stroke-width="1.2"/>'


def arrow(d: str, colour: str, marker: str, dashed: bool = False) -> str:
    dash = ' stroke-dasharray="5 5"' if dashed else ""
    return (
        f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="1.6"{dash} marker-end="url(#{marker})"/>'
    )


def marker(name: str, colour: str) -> str:
    return (
        f'<marker id="{name}" viewBox="0 0 8 8" refX="6.5" refY="4" markerWidth="8" markerHeight="8" '
        f'orient="auto-start-reverse"><path d="M0 0 L8 4 L0 8 z" fill="{colour}"/></marker>'
    )


# ---- small icons, drawn on a 24 by 24 grid ----


def icon(kind: str, x: float, y: float, colour: str) -> str:
    shapes = {
        # a script: a page with lines of code
        "script": '<path d="M6 3h9l4 4v14H6z M15 3v4h4"/><path d="M9 12l-2 2 2 2 M13 12l2 2-2 2"/>',
        # an agent session: a chat bubble with a spark
        "agent": '<path d="M4 5h16v11H11l-4 4v-4H4z"/><path d="M12 8v5 M9.5 10.5h5"/>',
        # a folder
        "folder": '<path d="M3 6h6l2 2h10v11H3z"/>',
        # a file
        "file": '<path d="M6 3h9l4 4v14H6z M15 3v4h4"/>',
        # a browser window
        "browser": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18 M6 6.5h.5 M8.5 6.5h.5"/>',
        # a person
        "person": '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c0-4 3-6 7-6s7 2 7 6"/>',
        # a plug: the MCP door
        "plug": '<path d="M9 3v5 M15 3v5 M7 8h10v3a5 5 0 0 1-10 0z M12 16v5"/>',
    }
    return (
        f'<g transform="translate({x} {y})" fill="none" stroke="{colour}" stroke-width="1.6" '
        f'stroke-linecap="round" stroke-linejoin="round">{shapes[kind]}</g>'
    )


# ---- the banner ----


MARK = Path(__file__).resolve().parents[1] / "src" / "loopcaptain" / "board" / "static" / "mark.svg"


def mark(x: float, y: float, size: float) -> str:
    """The logo, from its one source file, placed and scaled."""
    inner = MARK.read_text(encoding="utf-8").split(">", 1)[1].rsplit("</svg>", 1)[0]
    return f'<g transform="translate({x} {y}) scale({size / 64})">{inner}</g>'


def banner(theme: str) -> str:
    t = THEMES[theme]
    # The board's own picture: steps down, rounds across. A dot is a finished step, a number its
    # open findings (darker for more), the ring the step that runs now.
    rows = ["....", "....", "4321", "532.", "21..", "...o"]
    heat = {"1": 0.10, "2": 0.22, "3": 0.55, "4": 0.92, "5": 0.92}
    cells = []
    for row, line in enumerate(rows):
        for col, key in enumerate(line):
            x, y = 962 + col * 44, 76 + row * 34
            if key == ".":
                cells.append(f'<circle cx="{x + 17}" cy="{y + 13}" r="5" fill="{t["good"]}"/>')
            elif key == "o":
                cells.append(
                    f'<circle cx="{x + 17}" cy="{y + 13}" r="5.5" fill="none" stroke="{t["blue"]}" stroke-width="3"/>'
                )
            else:
                dark = heat[key] > 0.5
                cells.append(
                    f'<rect x="{x}" y="{y}" width="34" height="26" rx="7" fill="{t["ink"]}" fill-opacity="{heat[key]}"/>'
                    f'<text x="{x + 17}" y="{y + 18}" font-size="13" font-weight="700" text-anchor="middle" '
                    f'fill="{t["paper"] if dark else t["ink"]}" font-family="{FONT}">{key}</text>'
                )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="340" viewBox="0 0 1200 340" role="img" aria-label="Loopcaptain: an open protocol for agent loops and a local dashboard to monitor and steer them. A loop writes three small files; the board shows where it stands and takes your answer.">
  <title>Loopcaptain</title>
  <rect width="1200" height="340" fill="{t["paper"]}"/>
  <rect y="339" width="1200" height="1" fill="{t["hair"]}"/>
  {mark(66, 72, 84)}
  <g font-family="{FONT}">
    {text(172, 141, "Loopcaptain", 84, t["ink"], 700, 'letter-spacing="-3.4"')}
    {text(68, 208, "One board for every agent loop", 22, t["ink"], 600, 'letter-spacing="-0.4"')}
    {text(68, 242, "A loop writes three small files. The board shows where it stands,", 16.5, t["grey"])}
    {text(68, 267, "round by round, and takes your answer. No loop needs this repository.", 16.5, t["grey"])}
    {text(962, 56, "ROUNDS", 11, t["grey"], 600, 'letter-spacing="1.2"')}
    {text(962, 300, "a step per row, its open findings", 12, t["grey"])}
  </g>
  {"".join(cells)}
</svg>
"""


# ---- how it works ----


def hero(theme: str) -> str:
    t = THEMES[theme]
    ink, grey, accent = t["ink"], t["grey"], t["accent"]
    parts = [
        f'<rect width="1200" height="470" fill="{t["paper"]}"/>',
        f"<defs>{marker('tip', grey)}{marker('tip-red', accent)}</defs>",
        f'<g font-family="{FONT}">',
        # column titles
        text(40, 44, "A LOOP, IN ANY REPOSITORY", 11, grey, 600, 'letter-spacing="1.6"'),
        text(440, 44, "ITS FOLDER: THE WHOLE INTERFACE", 11, grey, 600, 'letter-spacing="1.6"'),
        text(840, 44, "THE BOARD, ON THIS MACHINE", 11, grey, 600, 'letter-spacing="1.6"'),
        # left: the two kinds of loop
        card(40, 64, 300, 118, t),
        icon("script", 58, 82, ink),
        text(94, 100, "A loop with a script", 16, ink, 600),
        text(58, 130, "Pastes the helper from LOOPS.md,", 13, grey),
        text(58, 149, "50 lines, standard library. One call", 13, grey),
        text(58, 168, "per step: emit(loop, event, fields).", 13, grey),
        card(40, 204, 300, 118, t),
        icon("agent", 58, 222, ink),
        text(94, 240, "A loop an agent session drives", 16, ink, 600),
        text(58, 270, "Uses the loopcaptain MCP server:", 13, grey),
        text(58, 289, "loop_register, emit,", 13, grey),
        text(58, 308, "inbox_read, loop_status.", 13, grey),
        icon("plug", 304, 286, grey),
        # middle: the folder
        card(440, 64, 300, 258, t, "sunk"),
        icon("folder", 458, 82, ink),
        f'<text x="494" y="100" font-size="14" font-weight="600" fill="{ink}" font-family="{MONO}">.loops/&lt;loop-id&gt;/</text>',
    ]
    files = [
        ("loop.json", "what the loop is: brief, steps, caps", 126),
        ("events.jsonl", "what happened, one line each", 190),
        ("inbox.jsonl", "what the person sends", 254),
    ]
    for name, what, y in files:
        parts += [
            card(458, y, 264, 52, t),
            icon("file", 468, y + 14, accent if name == "inbox.jsonl" else ink),
            f'<text x="500" y="{y + 23}" font-size="13.5" font-weight="600" fill="{ink}" font-family="{MONO}">{name}</text>',
            text(500, y + 41, what, 12.5, grey),
        ]
    parts += [
        # right: the board
        card(840, 64, 320, 258, t),
        icon("browser", 858, 82, ink),
        text(894, 100, "Loopcaptain", 16, ink, 600),
        f'<text x="1142" y="100" font-size="12" fill="{grey}" text-anchor="end" font-family="{MONO}">127.0.0.1:8484</text>',
        text(858, 132, "1  Every loop: status, rounds, cost,", 13, grey),
        text(858, 151, "    what waits for you", 13, grey),
        text(858, 176, "2  One loop: brief, the graph of a round,", 13, grey),
        text(858, 195, "    every round against every step,", 13, grey),
        text(858, 214, "    findings, files, items checked", 13, grey),
        text(858, 239, "3  Connect a loop: the protocol to copy", 13, grey),
        f'<rect x="858" y="262" width="284" height="42" rx="6" fill="{ink}"/>',
        text(874, 288, "Answer · Stop after this round · Start", 13, t["paper"], 600),
        # arrows: loops write, board reads, board writes the inbox, loop reads it
        arrow("M 340 123 C 390 123, 395 152, 452 152", grey, "tip"),
        arrow("M 340 263 C 390 263, 395 216, 452 216", grey, "tip"),
        text(352, 196, "write", 12, grey),
        arrow("M 722 152 C 780 152, 780 150, 834 150", grey, "tip"),
        arrow("M 722 216 C 780 216, 780 190, 834 190", grey, "tip"),
        text(752, 140, "reads", 12, grey),
        arrow("M 840 283 C 790 283, 780 280, 728 280", accent, "tip-red"),
        text(748, 304, "writes", 12, accent, 600),
        arrow("M 458 300 C 400 345, 250 350, 190 328", accent, "tip-red", dashed=True),
        text(246, 366, "the loop reads your answer at its next round", 12, accent, 600),
        # the person
        icon("person", 988, 356, ink),
        text(1022, 374, "you", 14, ink, 600),
        arrow("M 1000 352 V 328", grey, "tip"),
        # footer line
        f'<rect x="40" y="410" width="1120" height="1" fill="{t["hair"]}"/>',
        text(
            40,
            440,
            "The files are the truth: no server between loop and board, no database, nothing leaves the laptop.",
            14,
            grey,
        ),
        "</g>",
    ]
    label = (
        "How it works. On the left, a loop in any repository: a script that pastes the helper from "
        "LOOPS.md, or an agent session that uses the loopcaptain MCP server. Both write the loop's "
        "folder, .loops/loop-id, with three files: loop.json, events.jsonl and inbox.jsonl. On the "
        "right, the board on this machine reads the folder and shows every loop, one loop in detail, "
        "and the protocol to copy. Your answer, a stop or a start goes back through inbox.jsonl, which "
        "the loop reads at its next round."
    )
    body = "\n  ".join(parts)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="470" viewBox="0 0 1200 470" role="img" aria-label="{label}">
  <title>How Loopcaptain works</title>
  {body}
</svg>
"""


# ---- the parts, file by file (docs/ARCHITECTURE.md) ----

TILE_HEIGHT = 58
TILE_STEP = 68
GROUP_HEAD = 40
GROUP_WIDTH = 320
LIFT = 6


def group_height(tiles: int) -> int:
    return GROUP_HEAD + tiles * TILE_STEP + 2


def group(x: int, y: int, title: str, tiles: list[tuple[str, str, str]], t: dict[str, str]) -> str:
    """A lifted background tile with its flat tiles: each is (name, what it does, look).

    The look is `mono` for a file of this repository, `plain` for anything else, `key` for a tile
    that carries the logic and `file` for one of the loop's three files.
    """
    h = group_height(len(tiles))
    parts = [
        f'<rect x="{x}" y="{y + LIFT}" width="{GROUP_WIDTH}" height="{h}" rx="20" fill="{t["edge"]}" filter="url(#lift)"/>',
        f'<rect x="{x}" y="{y}" width="{GROUP_WIDTH}" height="{h}" rx="20" fill="{t["group"]}" stroke="{t["hair"]}"/>',
        text(x + 18, y + 26, title, 11, t["grey"], 600, 'letter-spacing="1.4"'),
    ]
    for row, (name, what, look) in enumerate(tiles):
        ty = y + GROUP_HEAD + row * TILE_STEP
        stroke, width = (t["accent"], 2) if look == "key" else (t["hair"], 1.2)
        family = FONT if look == "plain" else MONO
        left = x + 48 if look == "file" else x + 26
        parts.append(
            f'<rect x="{x + 12}" y="{ty}" width="{GROUP_WIDTH - 24}" height="{TILE_HEIGHT}" rx="12" '
            f'fill="{t["card"]}" stroke="{stroke}" stroke-width="{width}"/>'
        )
        if look == "file":
            parts.append(icon("file", x + 20, ty + 17, t["accent"] if name == "inbox.jsonl" else t["ink"]))
        parts.append(
            f'<text x="{left}" y="{ty + 24}" font-size="13.5" font-weight="600" fill="{t["ink"]}" '
            f'font-family="{family}">{name}</text>'
        )
        parts.append(text(left, ty + 43, what, 12.5, t["grey"]))
    return "".join(parts)


def parts_picture(theme: str) -> str:
    t = THEMES[theme]
    grey, accent = t["grey"], t["accent"]
    left, middle, right = 40, 440, 840
    top, low = 70, 410
    loops = [
        ("A loop with a script", "pastes standard/loops.py: emit, inbox", "plain"),
        ("A loop an agent session drives", "any coding agent that speaks MCP", "plain"),
        ("A shell loop", "calls the command line once per step", "plain"),
    ]
    ways = [
        ("mcp_server/server.py", "five tools over stdio", "mono"),
        ("cli.py", "emit: one event from a shell loop", "mono"),
    ]
    folder = [
        ("loop.json", "the brief, the steps, the caps, start", "file"),
        ("events.jsonl", "what happened, one line each", "file"),
        ("inbox.jsonl", "your answer, a note, a stop", "file"),
    ]
    protocol = [
        ("store.py", "atomic write, append, tolerant read", "mono"),
        ("models.py", "the manifest, the events, an inbox line", "mono"),
        ("state.py  fold()", "lines in: rounds, findings, status out", "key"),
        ("validate.py", "problems and warnings for a loop", "mono"),
    ]
    board = [
        ("discover.py", "the repositories you chose to watch", "mono"),
        ("app.py", "routes, host and token guards, CSP", "key"),
        ("graph.py", "a round's steps as columns and curves", "mono"),
        ("templates/ + static/", "overview, loop, file, connect", "mono"),
        ("steer.py  Runner", "runs commands.start, no shell", "mono"),
    ]
    ways_top = top + TILE_STEP
    row_1_bottom = top + group_height(3)
    you_y = low + 34
    height = low + group_height(len(board)) + LIFT + 86
    body = [
        f'<rect width="1200" height="{height}" fill="{t["paper"]}"/>',
        "<defs>",
        marker("tip", grey),
        marker("tip-red", accent),
        f'<filter id="lift" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="10" '
        f'stdDeviation="9" flood-color="{t["shade"]}" flood-opacity="0.16"/></filter>',
        "</defs>",
        f'<g font-family="{FONT}">',
        group(left, top, "A LOOP, IN ITS OWN REPOSITORY", loops, t),
        group(middle, ways_top, "WAYS IN WITHOUT A SCRIPT", ways, t),
        group(right, top, "THE LOOP'S FOLDER: THREE FILES", folder, t),
        group(right, low, "PROTOCOL/: THE STANDARD AS CODE", protocol, t),
        group(middle, low, "BOARD/: THIS MACHINE ONLY", board, t),
        # you: the one filled tile, where a person decides
        f'<rect x="{left}" y="{you_y + LIFT}" width="{GROUP_WIDTH}" height="96" rx="20" fill="{t["edge"]}" filter="url(#lift)"/>',
        f'<rect x="{left}" y="{you_y}" width="{GROUP_WIDTH}" height="96" rx="20" fill="{accent}"/>',
        icon("person", left + 20, you_y + 22, t["paper"]),
        text(left + 56, you_y + 42, "You, in the browser", 17, t["paper"], 600),
        text(
            left + 56,
            you_y + 66,
            "read a page, then answer, stop or start",
            12.5,
            t["paper"],
            400,
            'fill-opacity="0.85"',
        ),
        # a script writes the files itself, over the heads of the two ways in
        arrow(f"M {left + GROUP_WIDTH} {top + 50} H {right - 5}", grey, "tip"),
        text(
            600, top + 40, "writes loop.json, appends events.jsonl", 12.5, grey, 400, 'text-anchor="middle"'
        ),
        # a session and a shell loop go through the two ways in
        arrow(f"M {left + GROUP_WIDTH} {ways_top + 69} H {middle - 5}", grey, "tip"),
        text(400, ways_top + 60, "tool calls", 12, grey, 400, 'text-anchor="middle"'),
        arrow(f"M {left + GROUP_WIDTH} {ways_top + 137} H {middle - 5}", grey, "tip"),
        text(400, ways_top + 128, "emit", 12, grey, 400, 'text-anchor="middle"'),
        arrow(f"M {middle + GROUP_WIDTH} {ways_top + 69} H {right - 5}", grey, "tip"),
        arrow(f"M {middle + GROUP_WIDTH} {ways_top + 137} H {right - 5}", grey, "tip"),
        text(800, ways_top + 107, "same files", 12, grey, 400, 'text-anchor="middle"'),
        # the board reads the folder through the protocol
        arrow(f"M {right + 250} {row_1_bottom + LIFT} V {low - 5}", grey, "tip"),
        text(right + 240, low - 26, "read on every request", 12.5, grey, 400, 'text-anchor="end"'),
        arrow(f"M {right} {low + GROUP_HEAD + 2 * TILE_STEP + 29} H {middle + GROUP_WIDTH + 5}", grey, "tip"),
        text(800, low + GROUP_HEAD + 2 * TILE_STEP + 20, "state", 12, grey, 400, 'text-anchor="middle"'),
        arrow(f"M {middle + GROUP_WIDTH} {low + GROUP_HEAD + 29} H {right - 5}", grey, "tip"),
        text(800, low + GROUP_HEAD + 20, "which folders", 12, grey, 400, 'text-anchor="middle"'),
        # pages out, decisions in
        arrow(f"M {middle} {you_y + 34} H {left + GROUP_WIDTH + 5}", grey, "tip"),
        text(400, you_y + 25, "pages", 12, grey, 400, 'text-anchor="middle"'),
        arrow(f"M {left + GROUP_WIDTH} {you_y + 66} H {middle - 5}", accent, "tip-red"),
        text(400, you_y + 86, "decision", 12, accent, 600, 'text-anchor="middle"'),
        # the only two ways back into a loop: the inbox file and the loop's own start command
        arrow(
            f"M {middle + 250} {low} V {low - 34} H {right + 50} V {row_1_bottom + LIFT + 5}",
            accent,
            "tip-red",
        ),
        text(middle + 262, low - 14, "app.py appends inbox.jsonl", 12.5, accent, 600),
        arrow(
            f"M {right + 22} {row_1_bottom + LIFT} V {row_1_bottom + 30} H {left + 230} V {row_1_bottom + LIFT + 5}",
            accent,
            "tip-red",
            dashed=True,
        ),
        text(left + 244, row_1_bottom + 24, "the loop reads the inbox at its next round", 12.5, accent, 600),
        arrow(f"M {left + 90} {you_y} V {row_1_bottom + LIFT + 5}", grey, "tip", dashed=True),
        text(left + 102, you_y - 22, "Start: steer.py runs the", 12.5, grey),
        text(left + 102, you_y - 6, "command the loop declared", 12.5, grey),
        # what the picture says
        f'<rect x="40" y="{height - 58}" width="1120" height="1" fill="{t["hair"]}"/>',
        text(
            40,
            height - 26,
            "The board keeps no state of its own: every page is the three files, read again.",
            14,
            grey,
        ),
        "</g>",
    ]
    label = (
        "The parts of Loopcaptain, file by file. A loop in its own repository writes loop.json and "
        "appends events.jsonl, either from a script that pastes the helper, or through the MCP server "
        "or the command line, which write the same files. The board finds the watched repositories, "
        "reads the folder through protocol/store.py on every request, folds the lines into a state in "
        "protocol/state.py and renders pages. You read a page and decide: an answer or a stop is "
        "appended to inbox.jsonl by app.py, which the loop reads at its next round, and Start runs the "
        "one command the loop declared."
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}" '
        f'role="img" aria-label="{label}">\n  <title>The parts of Loopcaptain, file by file</title>\n  '
        + "\n  ".join(body)
        + "\n</svg>\n"
    )


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        for name, draw in (("banner", banner), ("hero", hero), ("parts", parts_picture)):
            path = ASSETS / f"{name}-{theme}.svg"
            path.write_text(draw(theme), encoding="utf-8")
            sys.stdout.write(f"{path.relative_to(ASSETS.parents[1])}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
