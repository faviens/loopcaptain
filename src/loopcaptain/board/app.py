"""The board: server-rendered pages over the loops' folders, on this machine only.

Every request reads the files again; there is no cache and no database. Every request must name
this server as its host and, the static files and the entry excepted, carry the session cookie
that the address printed by `serve` sets (`board/access.py`). Requests that change anything (a
reply, a stop, a start) are forms that also carry the token of this server process.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import posixpath
import secrets
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Annotated, cast
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from markupsafe import Markup

from loopcaptain.agents import agents, checkout_of
from loopcaptain.board.access import COOKIE_NAME, ENTER_PATH, HOST, Session, is_open, local_path
from loopcaptain.board.command import files_mark, named_files, read_command
from loopcaptain.board.discover import (
    Config,
    LoopView,
    Repo,
    find_loop,
    find_repo,
    find_repos,
    git_branch,
    load_config,
    load_loop,
    loops_of,
    put_aside,
    reason,
    unreadable_folders,
)
from loopcaptain.board.errors import add_error_pages, secured
from loopcaptain.board.files import TEXT_SUFFIXES, inside, is_named, named_paths, read_bounded
from loopcaptain.board.filters import ago, lead, minutes, place, stamp, tokens, usd
from loopcaptain.board.graph import layout
from loopcaptain.board.overview import APART, GROUPS, filter_views, group_of, projects_of, repeated_ids
from loopcaptain.board.steer import Runner
from loopcaptain.board.trend import CHART_ROUNDS, caps_of, charts_of, figure, trail_of
from loopcaptain.prompts import prompts
from loopcaptain.protocol import spec_text, store
from loopcaptain.protocol.models import EVENTS_FILE, INBOX_FILE, MANIFEST_FILE, FindingRef, Manifest, now
from loopcaptain.protocol.signing import board_keys, earlier_marks, is_from_board, read_board_keys
from loopcaptain.protocol.state import STATUS_TEXT, LoopState, RoundState, no_progress_signs
from loopcaptain.protocol.store import StoreError
from loopcaptain.protocol.validate import validate_loop

log = logging.getLogger("loopcaptain.web")

HERE = Path(__file__).parent
MAX_REPLY_CHARS = 20_000
#: The parts of a loop's page, each with its own address: ?tab=<name>.
#: How the person can settle a finding from the board, as the reply reads them. `fixed` and
#: `duplicate` are the loop's to say: only its own run shows them.
SETTLE_WORDS = {"accepted": "Accept as is", "wontfix": "Won't fix", "false_positive": "Not a problem"}
#: How long the header's figures may be reused while no loop's files change: statuses also move
#: with the clock (a silent round turns stalled), so not for longer.
TOTALS_FRESH_S = 5
#: The project's documentation site: the protocol, the guides and every command, explained at length.
DOCS_URL = "https://faviens.github.io/loopcaptain/"
TABS = ("overview", "rounds", "findings", "items", "inbox")
#: The two parts of the first page: every loop under its project, and what waits for the person.
OVERVIEW_TABS = ("loops", "waiting")
#: The statuses where "Stop after this round" means something: the loop may still start a round.
#: How many rounds the round grid draws at once, and how many rows a table of findings or
#: messages: a loop of thousands of rounds is still one page a browser can hold.
GRID_ROUNDS = 30
ROWS_SHOWN = 300
#: A status change further ahead than this is left to a later page load.
TURN_HORIZON = timedelta(days=7)
STOPPABLE = frozenset({"running", "sleeping", "stalled", "waiting", "idle"})
#: The statuses in which a loop is under way or has said when it is back.
STARTED_ELSEWHERE = frozenset({"running", "sleeping"})
#: Overview order: what needs the person first, then what moves, then the rest.
STATUS_ORDER = (
    "waiting",
    "failed",
    "stalled",
    "running",
    "sleeping",
    "capped",
    "idle",
    "stopped",
    "new",
    "done",
)

NextHandler = Callable[[Request], Awaitable[Response]]
STALE_FORM_TEXT = (
    "Nothing was sent: that page was drawn before the board last started. This one is fresh; send again."
)


class StaleForm(Exception):
    """A form that carries another server process's token, or none that this one made."""

    def __init__(self, repo_key: str, loop_id: str) -> None:
        super().__init__("a form from an older page")
        self.repo_key = repo_key
        self.loop_id = loop_id


MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable("table")


def asset_stamp() -> str:
    """A short digest of the stylesheet and the script: in their address, so a browser never keeps
    an old copy once either changes."""
    digest = hashlib.sha256()
    for name in ("style.css", "board.js"):
        digest.update((HERE / "static" / name).read_bytes())
    return digest.hexdigest()[:10]


def make_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters.update(
        ago=ago, usd=usd, minutes=minutes, tokens=tokens, stamp=stamp, place=place, figure=figure, lead=lead
    )
    templates.env.globals["status_text"] = STATUS_TEXT
    templates.env.globals["docs_url"] = DOCS_URL
    templates.env.globals["settle_words"] = SETTLE_WORDS
    templates.env.globals["asset_stamp"] = asset_stamp
    templates.env.globals["stoppable"] = STOPPABLE
    templates.env.globals["group_of"] = group_of
    templates.env.globals["no_progress"] = no_progress_signs
    templates.env.globals["trail_of"] = trail_of
    return templates


def create_app(
    config: Callable[[], Config] = load_config,
    runner: Runner | None = None,
    *,
    allowed_hosts: frozenset[str],
    session: Session | None = None,
) -> FastAPI:
    """The board. `allowed_hosts` is required: a board that answers to any host name can be reached
    by a web page that points its own name at this machine. `session` holds the key of the address
    that lets a browser in; without one the app makes its own and keeps it in `app.state.session`."""
    app = FastAPI(title="Loopcaptain", docs_url=None, redoc_url=None, openapi_url=None)
    templates = make_templates()
    steer = runner or Runner()
    token = secrets.token_urlsafe(24)
    app.state.token = token
    door = session or Session()
    app.state.session = door
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    add_error_pages(app, templates)

    @app.middleware("http")
    async def only_this_host(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        host = request.headers.get("host", "")
        if host not in allowed_hosts:
            return PlainTextResponse("this board answers only on its own address", status_code=400)
        if is_open(request.url.path) or door.admits(request.cookies):
            response = await call_next(request)
        else:
            response = locked(request)
        return secured(response)

    def locked(request: Request, spent: bool = False) -> Response:
        """What a browser without the cookie gets, whatever it asked for: where to find the address,
        or, for an address used already, how to get a new one."""
        return templates.TemplateResponse(request, "locked.html", {"spent": spent}, status_code=401)

    @app.get(ENTER_PATH, name="enter")
    def enter(request: Request, key: str = "", next: str = "/") -> Response:
        if door.admits(request.cookies):
            return RedirectResponse(local_path(next), status_code=303)
        if not door.opens(key):
            return locked(request)
        cookie = door.issue()
        if cookie is None:
            return locked(request, spent=True)
        response = RedirectResponse(local_path(next), status_code=303)
        response.set_cookie(door.cookie_name, cookie, httponly=True, samesite="strict", path="/")
        return response

    def problems_of(repo: Repo, loop_id: str) -> list[str]:
        """What is wrong with a loop the board lists but cannot load, in the words of `validate`."""
        try:
            return validate_loop(repo.path, loop_id).problems or ["loop.json cannot be read"]
        except Exception as error:
            return [f"loop.json cannot be read: {reason(error)}"]

    def check_token(given: str, repo_key: str, loop_id: str) -> None:
        if not hmac.compare_digest(given.encode(), token.encode()):
            raise StaleForm(repo_key, loop_id)

    @app.exception_handler(StaleForm)
    def stale_form(request: Request, problem: StaleForm) -> Response:
        """A form from a page drawn before this board started: nothing is done, the loop's page says so."""
        return back(problem.repo_key, problem.loop_id, error=STALE_FORM_TEXT)

    def view_of(repo_key: str, loop_id: str) -> tuple[Repo, Manifest, LoopView]:
        found = find_loop(config(), repo_key, loop_id)
        if found is None:
            raise HTTPException(404, "no such loop on this board")
        repo, manifest = found
        process = steer.process(repo, loop_id)
        return repo, manifest, load_loop(repo, loop_id, process_alive=bool(process and process.alive))

    def all_views() -> list[LoopView]:
        views = []
        cfg = config()
        for repo in find_repos(cfg):
            for home, loop_id in loops_of(repo):
                process = steer.process(home, loop_id)
                view = load_loop(home, loop_id, process_alive=bool(process and process.alive))
                views.append(replace(view, hidden=put_aside(cfg, home, loop_id)))
        return views

    def same_id_elsewhere(repo_key: str, loop_id: str) -> tuple[str, ...]:
        """The other watched repositories that have a loop with this id, by their keys."""
        pairs = ((repo.key, name) for repo in find_repos(config()) for name in store.loop_ids(repo.path))
        return tuple(key for key in repeated_ids(pairs).get(loop_id, ()) if key != repo_key)

    #: The views the header last counted, and the file stats and second they were read at: every
    #: page shows the board's figures, and a page that reloads itself must not re-read every loop.
    counted: dict[str, object] = {}

    def totals() -> dict[str, object] | None:
        """The board's figures for the header of every page; None where the loops cannot be read."""
        try:
            stamp = (overview_fingerprint(), int(time.monotonic() // TOTALS_FRESH_S))
            if counted.get("stamp") != stamp:
                counted.update(stamp=stamp, views=all_views())
            views = [view for view in cast(list[LoopView], counted["views"]) if not view.hidden]
        except Exception:  # the header must never take a page down, an error page least of all
            log.exception("the header's figures could not be read")
            return None
        states = [view.state for view in views if view.state]
        return {
            "loops": len(views),
            "projects": len({view.repo.key for view in views}),
            "waiting": sum(1 for state in states if state.question),
            "running": sum(1 for view in views if group_of(view) == "running"),
            "troubled": sum(1 for view in views if group_of(view) == "look"),
            "usd": sum(state.cost_usd for state in states),
        }

    templates.env.globals["totals"] = totals

    def waiting_now() -> int:
        """How many loops wait for the person: a tab in the background shows it in its title and
        says so in a notification, without drawing the page again."""
        figures = totals()
        return int(cast(int, figures["waiting"])) if figures else 0

    def overview_fingerprint() -> str:
        """From file stats alone, in discovery order: the overview polls it every few seconds. Which
        loops are hidden is part of it: `hide` changes the page and no loop's file."""
        cfg = config()
        states = [
            store.fingerprint(home.path, loop_id)
            for repo in find_repos(cfg)
            for home, loop_id in loops_of(repo)
        ]
        hidden = hashlib.sha256("\0".join(sorted(str(entry) for entry in cfg.hidden)).encode()).hexdigest()[
            :8
        ]
        return "|".join([*states, hidden])

    def seal(note: str, error: str) -> str:
        """A mark only this server process can make, so a crafted link cannot put words on a page."""
        return hmac.new(token.encode(), f"{note}\0{error}".encode(), "sha256").hexdigest()

    def back(
        repo_key: str, loop_id: str, note: str = "", error: str = "", *, tab: str = "", back_to: str = ""
    ) -> RedirectResponse:
        """To the loop's page, on the tab the form was drawn on, with a message only this server can seal.

        `back_to` names the one other place a form may lead: the overview's waiting tab. It is a name,
        never an address, so a form cannot send the browser anywhere the board does not know."""
        url = str(app.url_path_for("loop_page", repo_key=repo_key, loop_id=loop_id))
        pairs = [("tab", tab)] if tab in TABS and tab != "overview" else []
        if back_to == "waiting":
            url, pairs = str(app.url_path_for("overview")), [("tab", "waiting")]
        if note or error:
            pairs += [("note", note), ("error", error), ("seal", seal(note, error))]
        query = "&".join(f"{key}={quote(value)}" for key, value in pairs if value)
        return RedirectResponse(f"{url}?{query}" if query else url, status_code=303)

    def message_of(request: Request) -> tuple[str, str]:
        note = request.query_params.get("note", "")
        error = request.query_params.get("error", "")
        given = request.query_params.get("seal", "")
        return (note, error) if hmac.compare_digest(given.encode(), seal(note, error).encode()) else ("", "")

    @app.get("/", response_class=HTMLResponse, name="overview")
    def overview(
        request: Request,
        tab: str = "",
        q: str = "",
        status: Annotated[list[str] | None, Query()] = None,
        finished: str = "",
        show: str = "",
    ) -> Response:
        try:
            cfg = config()
            views = all_views()
            unreadable = unreadable_folders(cfg)
            error = ""
        except StoreError as problem:
            cfg, views, unreadable, error = Config(), [], [], str(problem)

        def rank(view: LoopView) -> tuple[int, float]:
            status = view.state.status if view.state else "failed"
            last = view.state.last_event if view.state else None
            return STATUS_ORDER.index(status), -(last.timestamp() if last else 0.0)

        note, told = message_of(request)
        views.sort(key=rank)
        # A figure asks for more than one status as the status given twice, the menu as one value
        # joined by commas, so Filter keeps them; an unknown one is dropped.
        asked = {part for value in status or () for part in value.split(",")}
        statuses = frozenset(asked) & frozenset(STATUS_ORDER)
        shown, hidden = filter_views(views, q, statuses, show_finished=finished == "1")
        found, _ = filter_views(views, q, frozenset(), show_finished=True)
        groups: Counter[str] = Counter(group_of(view) for view in found)
        group = show if show in GROUPS else ""
        if group:  # one group, finished or not, whatever else the address says
            shown, hidden = [view for view in found if group_of(view) == group], 0
        else:
            shown = [view for view in shown if group_of(view) not in APART]
        seen = [view for view in views if not view.hidden]  # what the figures and the waiting tab count
        context = {
            "views": views,
            "projects": projects_of(shown),
            "project_count": len({view.repo.key for view in seen}),
            "hidden": hidden,
            "groups": GROUPS,
            "group_counts": groups,
            "filters": {
                "q": q,
                "statuses": statuses,
                "together": [name for name in STATUS_ORDER if name in statuses] if len(statuses) > 1 else [],
                "finished": finished == "1",
                "group": group,
            },
            "statuses": STATUS_ORDER,
            "prompts": prompts(),
            "tab": tab if tab in OVERVIEW_TABS else "loops",
            "waiting": [view for view in seen if view.state and view.state.question],
            "waiting_projects": projects_of([view for view in seen if view.state and view.state.question]),
            "config": cfg,
            "error": error or told,
            "note": note,
            "unreadable": unreadable,
            "repeated": repeated_ids((view.repo.key, view.loop_id) for view in views),
            "token": token,
            "pulse": overview_fingerprint() if not error else "error",
            "turn_at": turn_at(views),
            "total_usd": sum(view.state.cost_usd for view in seen if view.state),
        }
        return templates.TemplateResponse(request, "overview.html", context)

    @app.get("/pulse", name="overview_pulse")
    def overview_pulse() -> JSONResponse:
        try:
            return JSONResponse({"pulse": overview_fingerprint(), "waiting": waiting_now()})
        except StoreError:
            return JSONResponse({"pulse": "error"})

    @app.get("/loop/{repo_key}/{loop_id}", response_class=HTMLResponse, name="loop_page")
    def loop_page(
        request: Request, repo_key: str, loop_id: str, tab: str = "", round: int | None = None
    ) -> Response:
        found = find_loop(config(), repo_key, loop_id)
        broken = find_repo(config(), repo_key, loop_id) if found is None else None
        if broken is not None:
            # Listed, but its loop.json cannot be read: say what is wrong instead of a bare error.
            context = {"repo": broken, "loop_id": loop_id, "problems": problems_of(broken, loop_id)}
            return templates.TemplateResponse(request, "unreadable.html", context)
        repo, manifest, view = view_of(repo_key, loop_id)
        note, error = message_of(request)
        state = view.state
        if state is None:
            context = {"repo": repo, "loop_id": loop_id, "problems": [view.error]}
            return templates.TemplateResponse(request, "unreadable.html", context)
        manifest = state.manifest  # as the fold counts it: a cost cap that is not finite is none
        shown = next((r for r in state.rounds if r.number == round), state.last_round)
        process = steer.process(repo, loop_id)
        declared = read_command(manifest.commands.get("start", ""))
        context = {
            "view": view,
            "state": state,
            "manifest": manifest,
            "shown": shown,
            # A link to a round opens the rounds tab; an unknown tab is the overview.
            "tab": tab if tab in TABS else ("rounds" if round is not None else "overview"),
            "hidden": put_aside(config(), repo, loop_id),
            "grid": round_window(state.rounds, shown),
            "rows_shown": ROWS_SHOWN,
            "chart_rounds": CHART_ROUNDS,
            "graph": layout(manifest, shown) if manifest.steps else None,
            "branch": git_branch(repo.path),
            "process": process,
            "log_tail": steer.log_tail(repo, loop_id) if process else "",
            "command": declared,
            "files_mark": files_mark(named_files(repo.path, declared.argv)),
            "confirmed": steer.is_confirmed(repo, loop_id, manifest.commands.get("start", "")),
            "changed_files": steer.changed_files(repo, loop_id, manifest.commands.get("start", "")),
            "runs_elsewhere": runs_elsewhere(view, steer),
            "same_id": same_id_elsewhere(repo.key, loop_id),
            "signed": inbox_marks(repo, state),
            "charts": charts_of(state),
            "stuck": no_progress_signs(state),
            "report": validate_loop(repo.path, loop_id),
            "caps": caps_of(state),
            "token": token,
            "pulse": pulse_of(repo, loop_id, steer),
            "turn_at": turn_at([view]),
            "note": note,
            "error": error,
        }
        return templates.TemplateResponse(request, "loop.html", context)

    @app.get("/loop/{repo_key}/{loop_id}/pulse", name="loop_pulse")
    def loop_pulse(repo_key: str, loop_id: str) -> JSONResponse:
        found = find_loop(config(), repo_key, loop_id)
        if found is None:
            raise HTTPException(404, "no such loop on this board")
        return JSONResponse({"pulse": pulse_of(found[0], loop_id, steer), "waiting": waiting_now()})

    @app.get("/loop/{repo_key}/{loop_id}/file", response_class=HTMLResponse, name="loop_file")
    def loop_file(request: Request, repo_key: str, loop_id: str, path: str) -> Response:
        repo, manifest, view = view_of(repo_key, loop_id)
        # One spelling for the check and for the read: `a/../x` names `x`, whatever `a` links to.
        path = posixpath.normpath(path)
        if not is_named(path, files_of(repo, manifest)):
            raise HTTPException(404, "this loop names no such file")
        target = inside(repo.path, path)
        body: Markup | None = None
        text = ""
        reason = ""
        if target.suffix.lower() not in TEXT_SUFFIXES:
            reason = "not shown: the board opens only text files it knows"
        else:
            try:
                size, data = read_bounded(repo.path, target)
            except OSError as problem:
                # Gone, or turned into a link, since the path was checked.
                raise HTTPException(404, "no such file in this repository") from problem
            if data is None:
                reason = f"{size // 1000} kB: too large to show here"
            else:
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    reason = "not a text file"
        if not reason and target.suffix.lower() in {".md", ".markdown"}:
            body = Markup(MARKDOWN.render(text))
        context = {
            "view": view,
            "manifest": manifest,
            "path": path,
            "body": body,
            "text": text,
            "reason": reason,
        }
        return templates.TemplateResponse(request, "file.html", context)

    @app.post("/loop/{repo_key}/{loop_id}/reply", name="loop_reply")
    def loop_reply(
        repo_key: str,
        loop_id: str,
        token: Annotated[str, Form()],
        tab: Annotated[str, Form()] = "",
        back_to: Annotated[str, Form()] = "",
        text: Annotated[str, Form()] = "",
        choice: Annotated[str, Form()] = "",
        asked_at: Annotated[str, Form()] = "",
    ) -> Response:
        check_token(token, repo_key, loop_id)
        repo, _, view = view_of(repo_key, loop_id)
        asked = view.state.question if view.state else None
        if asked_at and (asked is None or asked.asked.isoformat() != asked_at):
            # The page was drawn for another asking: the loop has asked again, or something else, since.
            return back(
                repo_key,
                loop_id,
                tab=tab,
                back_to=back_to,
                error="Nothing was sent: the loop no longer asks the question this answered.",
            )
        picked = next((option for option in asked.options if option.id == choice), None) if asked else None
        if choice and picked is None:
            return back(
                repo_key,
                loop_id,
                tab=tab,
                back_to=back_to,
                error="Nothing was sent: that choice is no longer offered.",
            )
        message = text.strip() or (picked.label if picked else "")
        if not message:
            return back(
                repo_key, loop_id, tab=tab, back_to=back_to, error="Nothing was sent: the reply was empty."
            )
        if len(message) > MAX_REPLY_CHARS:
            return back(
                repo_key,
                loop_id,
                tab=tab,
                back_to=back_to,
                error=f"Nothing was sent: over {MAX_REPLY_CHARS} characters.",
            )
        question = view.state.question if view.state else None
        last = view.state.last_round if view.state else None
        round_ = question.round if question and question.round else (last.number if last else None)
        try:
            store.append_inbox(
                repo.path,
                loop_id,
                "reply",
                message,
                round_,
                keys=board_keys(),
                question=asked.id if asked else None,
                choice=picked.id if picked else None,
            )
        except StoreError as problem:
            return back(repo_key, loop_id, tab=tab, back_to=back_to, error=str(problem))
        status = view.state.status if view.state else ""
        ended = status in ("done", "failed", "stopped", "capped")
        when = f"when it is started again: it is {status} now" if ended else "at its next round"
        return back(repo_key, loop_id, tab=tab, back_to=back_to, note=f"Sent. The loop reads it {when}.")

    @app.post("/loop/{repo_key}/{loop_id}/finding", name="loop_settle")
    def loop_settle(
        repo_key: str,
        loop_id: str,
        token: Annotated[str, Form()],
        step: Annotated[str, Form()],
        finding: Annotated[str, Form()],
        resolution: Annotated[str, Form()],
        label: Annotated[str, Form()] = "",
        reason: Annotated[str, Form()] = "",
        tab: Annotated[str, Form()] = "findings",
    ) -> Response:
        """The person settles one open finding: a signed reply naming it, for the loop to close."""
        check_token(token, repo_key, loop_id)
        repo, _, view = view_of(repo_key, loop_id)
        state = view.state
        found = next(
            (
                (run, item)
                for run, item in (state.open_findings if state else ())
                if run.step == step and item.id == finding and run.label == label
            ),
            None,
        )
        if found is None or resolution not in SETTLE_WORDS:
            return back(
                repo_key, loop_id, tab="findings", error="Nothing was sent: that finding is no longer open."
            )
        run, item = found
        pending = state.settling(run, item) if state else None
        if pending and not pending.read:
            return back(
                repo_key,
                loop_id,
                tab=tab,
                note="Already sent. The loop closes the finding at its next round.",
            )
        reason = reason.strip()[:MAX_REPLY_CHARS]
        said = f"{SETTLE_WORDS[resolution]}: {item.text}"[:MAX_REPLY_CHARS]
        ref = FindingRef(step=step, id=finding, label=label or None, resolution=resolution, reason=reason)  # type: ignore[arg-type]
        try:
            store.append_inbox(
                repo.path,
                loop_id,
                "reply",
                said + (f" Why: {reason}" if reason else ""),
                state.last_round.number if state and state.last_round else None,
                keys=board_keys(),
                finding=ref,
            )
        except StoreError as problem:
            return back(repo_key, loop_id, tab="findings", error=str(problem))
        return back(
            repo_key, loop_id, tab="findings", note="Sent. The loop closes the finding at its next round."
        )

    @app.post("/loop/{repo_key}/{loop_id}/stop", name="loop_stop")
    def loop_stop(
        repo_key: str, loop_id: str, token: Annotated[str, Form()], tab: Annotated[str, Form()] = ""
    ) -> Response:
        check_token(token, repo_key, loop_id)
        repo, _, view = view_of(repo_key, loop_id)
        if view.state and view.state.stop_requested:
            return back(repo_key, loop_id, tab=tab, note="A stop is already waiting for the loop.")
        if view.state and view.state.status not in STOPPABLE:
            # Nothing would read it now, and the next start would read it and end at once.
            status = view.state.status
            return back(
                repo_key,
                loop_id,
                tab=tab,
                error=f"No stop was sent: this loop is {status} and starts no further round by itself.",
            )
        try:
            store.append_inbox(repo.path, loop_id, "stop", keys=board_keys())
        except StoreError as problem:
            return back(repo_key, loop_id, tab=tab, error=str(problem))
        under_way = view.state is not None and view.state.status in ("running", "stalled", "waiting")
        then = "ends after its current round" if under_way else "reads it at its next start and runs no round"
        return back(repo_key, loop_id, tab=tab, note=f"Stop sent. The loop {then}.")

    @app.post("/loop/{repo_key}/{loop_id}/start", name="loop_start")
    def loop_start(
        repo_key: str,
        loop_id: str,
        token: Annotated[str, Form()],
        tab: Annotated[str, Form()] = "",
        command: Annotated[str, Form()] = "",
        confirm: Annotated[str, Form()] = "",
        again: Annotated[str, Form()] = "",
        files: Annotated[str, Form()] = "",
    ) -> Response:
        check_token(token, repo_key, loop_id)
        repo, manifest, view = view_of(repo_key, loop_id)
        if command != manifest.commands.get("start", ""):
            # The loop rewrote its command after the page was drawn: run only what the person saw.
            return back(
                repo_key,
                loop_id,
                tab=tab,
                error="Not started: the start command changed. Check it and press again.",
            )
        if command and runs_elsewhere(view, steer) and again != "yes":
            return back(
                repo_key,
                loop_id,
                tab=tab,
                error="Not started: this loop is under way and the board did not start it. "
                "A second copy would write the same files. Tick the box to start one anyway.",
            )
        first = not steer.is_confirmed(repo, loop_id, command)
        if first and confirm != "yes":
            return back(
                repo_key,
                loop_id,
                tab=tab,
                error="Not started: first start of this command. Read it, tick the box, press again.",
            )
        # Read before the process begins: what is remembered is what the page told the person of.
        named = named_files(repo.path, read_command(command).argv)
        if files_mark(named) != files:
            return back(
                repo_key,
                loop_id,
                tab=tab,
                error="Not started: a file the command names changed after this page was drawn. "
                "Look at it and press again.",
            )
        try:
            process = steer.start(repo, manifest)
        except StoreError as problem:
            return back(repo_key, loop_id, tab=tab, error=f"Not started: {problem}.")
        steer.confirm(repo, loop_id, command, named)  # every start: the files are remembered anew
        return back(repo_key, loop_id, tab=tab, note=f"Started: {process.command} (pid {process.pid}).")

    @app.post("/loop/{repo_key}/{loop_id}/kill", name="loop_kill")
    def loop_kill(
        repo_key: str, loop_id: str, token: Annotated[str, Form()], tab: Annotated[str, Form()] = ""
    ) -> Response:
        check_token(token, repo_key, loop_id)
        repo, _, _ = view_of(repo_key, loop_id)
        try:
            ended = steer.kill(repo, loop_id)
        except StoreError as problem:
            return back(repo_key, loop_id, tab=tab, error=f"{problem}.".capitalize())
        if not ended:
            return back(repo_key, loop_id, tab=tab, note="The process had already ended: nothing was sent.")
        return back(repo_key, loop_id, tab=tab, note="The process was told to end.")

    @app.get("/connect", response_class=HTMLResponse, name="connect")
    def connect(request: Request, agent: str = "") -> Response:
        spec = spec_text()
        known = agents(checkout_of(HERE.parents[2]))
        picked = next((item for item in known if item.key == agent), known[0])
        context = {
            "spec": spec,
            "body": Markup(MARKDOWN.render(spec)),
            "agents": known,
            "picked": picked,
            "prompts": prompts(),
        }
        return templates.TemplateResponse(request, "connect.html", context)

    @app.get("/connect/LOOPS.md", name="spec_file")
    def spec_file() -> PlainTextResponse:
        return PlainTextResponse(spec_text(), media_type="text/markdown; charset=utf-8")

    return app


def runs_elsewhere(view: LoopView, steer: Runner) -> bool:
    """Whether a loop reads as under way although no process the board started is alive: someone
    started it from a terminal or a schedule, and a Start here would run a second copy beside it."""
    if view.state is None or view.state.status not in STARTED_ELSEWHERE:
        return False
    process = steer.process(view.repo, view.loop_id)
    return not (process and process.alive)


def files_of(repo: Repo, manifest: Manifest) -> frozenset[str]:
    """The files this loop names: in its `loop.json`, in its events, and as arguments of its start
    command, and the three files that are the loop. The board opens no other file of the repository."""
    events, _ = store.read_events(repo.path, manifest.id)
    records = [manifest.model_dump(mode="json"), *(event.model_dump(mode="json") for event in events)]
    command = read_command(manifest.commands.get("start", ""))
    folder = store.loop_dir(repo.path, manifest.id).relative_to(repo.path).as_posix()
    own = frozenset(f"{folder}/{name}" for name in (MANIFEST_FILE, EVENTS_FILE, INBOX_FILE))
    return named_paths(records) | frozenset(named_files(repo.path, command.argv)) | own


def inbox_marks(repo: Repo, state: LoopState) -> dict[str, bool | None]:
    """For each inbox entry, whether this board signed it; None where the board has no key yet."""
    keys, loop_id = read_board_keys(), state.manifest.id
    folder = store.loop_dir(repo.path, loop_id)
    earlier = earlier_marks(folder)
    return {
        item.entry.id: is_from_board(item.entry.body(), keys, folder, loop_id, earlier)
        for item in state.inbox
    }


@dataclass(frozen=True)
class RoundWindow:
    """The rounds one page draws as columns, and the round to ask for to see the ones before or after."""

    rounds: tuple[RoundState, ...]
    earlier: int | None = None
    later: int | None = None


def round_window(rounds: tuple[RoundState, ...], shown: RoundState | None) -> RoundWindow:
    """The stretch of at most GRID_ROUNDS rounds that holds the round shown, counted in whole
    stretches from the latest round back, so the newest stretch is always full."""
    place = next(
        (n for n, round_ in enumerate(rounds) if shown and round_.number == shown.number), len(rounds) - 1
    )
    end = len(rounds) - (len(rounds) - 1 - place) // GRID_ROUNDS * GRID_ROUNDS
    start = max(0, end - GRID_ROUNDS)
    return RoundWindow(
        rounds[start:end],
        earlier=rounds[start - 1].number if start > 0 else None,
        later=rounds[min(end + GRID_ROUNDS, len(rounds)) - 1].number if end < len(rounds) else None,
    )


def turn_at(views: list[LoopView]) -> int | None:
    """The next moment, in epoch seconds, at which one of these loops changes status with no file
    written: a sleeping loop's promise runs out. The pulse is built from file stats and cannot
    know it, so the page is told when to look again. None where no such moment lies ahead."""
    at = now()
    ahead = [
        view.state.turns_at
        for view in views
        if view.state and view.state.turns_at and at < view.state.turns_at <= at + TURN_HORIZON
    ]
    return int(min(ahead).timestamp()) + 1 if ahead else None


def pulse_of(repo: Repo, loop_id: str, steer: Runner) -> str:
    process = steer.process(repo, loop_id)
    alive = "1" if process and process.alive else "0"
    try:
        log_size = steer.log_path(repo, loop_id).stat().st_size
    except OSError:
        log_size = 0
    return f"{store.fingerprint(repo.path, loop_id)}.{alive}.{log_size}"


def session_for(port: int) -> Session:
    """A new key for a board on this port. Browsers keep one cookie jar per host name, whatever the
    port, so the cookie is named after the port and two boards do not log each other out."""
    return Session(cookie_name=f"{COOKIE_NAME}-{port}")


def entry_address(port: int, session: Session) -> str:
    """The address `serve` prints: opening it lets that browser in."""
    return f"http://{HOST}:{port}{session.entry_path}"


def serve(port: int, session: Session) -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    hosts = frozenset({f"{HOST}:{port}", f"localhost:{port}"})
    uvicorn.run(create_app(allowed_hosts=hosts, session=session), host=HOST, port=port, log_level="warning")
