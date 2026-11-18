# board/: the front end

Read [the root AGENTS.md](../../../AGENTS.md) first. This folder is the
dashboard: a FastAPI app that renders pages on the server from the loops'
folders. No build step, no JavaScript framework, no database.

| File | Holds |
|---|---|
| `app.py` | The routes, the host and token guards, the content policy |
| `access.py` | The session: the key of the address `serve` prints, the cookie it sets, which paths are open without it |
| `errors.py` | What a refusal or a fault looks like: `error.html` for a browser, the same words as JSON for the page's script |
| `files.py` | Which files of a repository the viewer opens: the deny-list and the text suffixes |
| `filters.py` | How times, money, tokens and places read on a page |
| `overview.py` | The first page: loops grouped by repository, the text and status filters |
| `trend.py` | The small SVG line per measure and the bars against the caps |
| `discover.py` | Which repositories are watched (`loopcaptain.local.yaml`) and loading a loop into a `LoopView` |
| `graph.py` | The picture of one round: each step gets a column and a row; the template draws the SVG |
| `steer.py` | `Runner`: starts the one command a loop declares, remembers its pid, tails its log, ends it |
| `templates/` | `overview.html` (all loops), `loop.html` (one loop: the tabs Overview, Rounds, Open findings, Items, What you sent, chosen by `?tab=`), `unreadable.html` (a loop whose `loop.json` cannot be read), `locked.html` (a browser that has not opened the printed address), `error.html` (a refusal or a fault, with the reason and a way back), `file.html` (a file of the loop), `connect.html` (the standard), `base.html` |
| `static/` | `style.css` (the design tokens and every component), `mark.svg` (the logo, its one source), `board.js` (reload on change, a message shown once, copy button), `fonts/` (Inter and Inter Tight, vendored, SIL OFL) |

Rules here:

1. Pages are read fresh on every request; add no cache.
2. No inline `<script>`, `style=` or `on...=` in a template, and nothing
   from another origin: the content policy blocks it and
   `tests/test_board.py` checks it.
3. Design: the tokens at the top of `style.css` are the whole palette,
   type scale (12/14/16/20/26/36) and spacing (4/8 point). One action
   colour, one red on paper and ink: links, the answer button and "waiting
   for you", nothing decorative. Status colours only for status, and every status also has
   its own shape (dot, ring, bar, square), so the page reads without
   colour. Open findings are an ink ramp, darker for more. Dark mode only
   redefines tokens. Controls are at least 44 px high; text keeps 4.5:1.
   No company name, logo or colour anywhere: the board is neutral.
4. A route that changes anything is a POST form with the hidden `token`
   and calls `check_token` first.
   Every route sits behind the session cookie; a path is open without it
   only if `access.is_open` names it, and `tests/test_access.py` walks
   every route.
5. A file is shown only through `inside()`, which refuses any path that
   leaves the repository. Markdown renders with raw HTML off.
6. After a visible change, look at it: `make demo`, `make serve`, and
   retake the README screenshots if the page changed.
