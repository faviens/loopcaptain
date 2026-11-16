"""The board: server-rendered pages over the loops' folders, on this machine only.

Every request reads the files again; there is no cache and no database. Requests that change
anything (a reply, a stop, a start) are forms that carry the token of this server process, and
every request must name this server as its host, so a web page open in the same browser cannot
steer a loop.
"""

from __future__ import annotations

import hmac
import logging
import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from markupsafe import Markup

from loopcaptain.agents import agents, checkout_of
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
)
from loopcaptain.board.files import MAX_FILE_BYTES, TEXT_SUFFIXES, inside
from loopcaptain.board.filters import ago, minutes, place, stamp, tokens, usd
from loopcaptain.board.graph import layout
from loopcaptain.board.overview import filter_views, projects_of
from loopcaptain.board.steer import Runner
from loopcaptain.board.trend import caps_of, charts_of, figure, trail_of
from loopcaptain.prompts import prompts
from loopcaptain.protocol import spec_text, store
from loopcaptain.protocol.models import Manifest
from loopcaptain.protocol.signing import board_key, is_signed, read_key
from loopcaptain.protocol.state import STATUS_TEXT, LoopState, no_progress_signs
from loopcaptain.protocol.store import StoreError
from loopcaptain.protocol.validate import validate_loop

log = logging.getLogger("loopcaptain.web")

HERE = Path(__file__).parent
HOST = "127.0.0.1"
MAX_REPLY_CHARS = 20_000
#: The parts of a loop's page, each with its own address: ?tab=<name>.
TABS = ("overview", "rounds", "findings", "items", "inbox")
#: The two parts of the first page: every loop under its project, and what waits for the person.
OVERVIEW_TABS = ("loops", "waiting")
#: The statuses where "Stop after this round" means something: the loop may still start a round.
STOPPABLE = frozenset({"running", "sleeping", "stalled", "waiting", "idle"})
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

#: Everything the pages load comes from this server: no inline script or style, no other origin.
CONTENT_POLICY = (
    "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
NextHandler = Callable[[Request], Awaitable[Response]]

MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable("table")


def make_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters.update(
        ago=ago, usd=usd, minutes=minutes, tokens=tokens, stamp=stamp, place=place, figure=figure
    )
    templates.env.globals["status_text"] = STATUS_TEXT
    templates.env.globals["stoppable"] = STOPPABLE
    templates.env.globals["no_progress"] = no_progress_signs
    templates.env.globals["trail_of"] = trail_of
    return templates


def create_app(
    config: Callable[[], Config] = load_config,
    runner: Runner | None = None,
    *,
    allowed_hosts: frozenset[str],
) -> FastAPI:
    """The board. `allowed_hosts` is required: a board that answers to any host name can be reached
    by a web page that points its own name at this machine."""
    app = FastAPI(title="Loopcaptain", docs_url=None, redoc_url=None, openapi_url=None)
    templates = make_templates()
    steer = runner or Runner()
    token = secrets.token_urlsafe(24)
    app.state.token = token
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    @app.middleware("http")
    async def only_this_host(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        host = request.headers.get("host", "")
        if host not in allowed_hosts:
            return PlainTextResponse("this board answers only on its own address", status_code=400)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CONTENT_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    def check_token(given: str) -> None:
        if not hmac.compare_digest(given.encode(), token.encode()):
            raise HTTPException(403, "this form is from an older page; reload and send again")

    def view_of(repo_key: str, loop_id: str) -> tuple[Repo, Manifest, LoopView]:
        found = find_loop(config(), repo_key, loop_id)
        if found is None:
            raise HTTPException(404, "no such loop on this board")
        repo, manifest = found
        process = steer.process(repo, loop_id)
        return repo, manifest, load_loop(repo, loop_id, process_alive=bool(process and process.alive))

    def all_views() -> list[LoopView]:
        views = []
        for repo in find_repos(config()):
            for loop_id in store.loop_ids(repo.path):
                process = steer.process(repo, loop_id)
                views.append(load_loop(repo, loop_id, process_alive=bool(process and process.alive)))
        return views

    def overview_fingerprint() -> str:
        """From file stats alone, in discovery order: the overview polls it every few seconds."""
        return "|".join(
            store.fingerprint(repo.path, loop_id)
            for repo in find_repos(config())
            for loop_id in store.loop_ids(repo.path)
        )

    def seal(note: str, error: str) -> str:
        """A mark only this server process can make, so a crafted link cannot put words on a page."""
        return hmac.new(token.encode(), f"{note}\0{error}".encode(), "sha256").hexdigest()

    def back(repo_key: str, loop_id: str, note: str = "", error: str = "") -> RedirectResponse:
        url = str(app.url_path_for("loop_page", repo_key=repo_key, loop_id=loop_id))
        if not (note or error):
            return RedirectResponse(url, status_code=303)
        pairs = (("note", note), ("error", error), ("seal", seal(note, error)))
        query = "&".join(f"{key}={quote(value)}" for key, value in pairs if value)
        return RedirectResponse(f"{url}?{query}", status_code=303)

    def message_of(request: Request) -> tuple[str, str]:
        note = request.query_params.get("note", "")
        error = request.query_params.get("error", "")
        given = request.query_params.get("seal", "")
        return (note, error) if hmac.compare_digest(given.encode(), seal(note, error).encode()) else ("", "")

    @app.get("/", response_class=HTMLResponse, name="overview")
    def overview(
        request: Request, tab: str = "", q: str = "", status: str = "", finished: str = ""
    ) -> Response:
        try:
            cfg = config()
            views = all_views()
            error = ""
        except StoreError as problem:
            cfg, views, error = Config(), [], str(problem)

        def rank(view: LoopView) -> tuple[int, float]:
            status = view.state.status if view.state else "failed"
            last = view.state.last_event if view.state else None
            return STATUS_ORDER.index(status), -(last.timestamp() if last else 0.0)

        views.sort(key=rank)
        shown, hidden = filter_views(views, q, status, show_finished=finished == "1")
        context = {
            "views": views,
            "projects": projects_of(shown),
            "project_count": len({view.repo.key for view in views}),
            "hidden": hidden,
            "filters": {
                "q": q,
                "status": status if status in STATUS_ORDER else "",
                "finished": finished == "1",
            },
            "statuses": STATUS_ORDER,
            "prompts": prompts(),
            "tab": tab if tab in OVERVIEW_TABS else "loops",
            "waiting": [view for view in views if view.state and view.state.question],
            "config": cfg,
            "error": error,
            "token": token,
            "pulse": overview_fingerprint() if not error else "error",
            "total_usd": sum(view.state.cost_usd for view in views if view.state),
        }
        return templates.TemplateResponse(request, "overview.html", context)

    @app.get("/pulse", name="overview_pulse")
    def overview_pulse() -> JSONResponse:
        try:
            return JSONResponse({"pulse": overview_fingerprint()})
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
            problems = validate_loop(broken.path, loop_id).problems or ["loop.json cannot be read"]
            context = {"repo": broken, "loop_id": loop_id, "problems": problems}
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
        context = {
            "view": view,
            "state": state,
            "manifest": manifest,
            "shown": shown,
            # A link to a round opens the rounds tab; an unknown tab is the overview.
            "tab": tab if tab in TABS else ("rounds" if round is not None else "overview"),
            "graph": layout(manifest, shown) if manifest.steps else None,
            "branch": git_branch(repo.path),
            "process": process,
            "log_tail": steer.log_tail(repo, loop_id) if process else "",
            "confirmed": steer.is_confirmed(repo, manifest.commands.get("start", "")),
            "signed": inbox_marks(state),
            "charts": charts_of(state),
            "stuck": no_progress_signs(state),
            "report": validate_loop(repo.path, loop_id),
            "caps": caps_of(state),
            "token": token,
            "pulse": pulse_of(repo, loop_id, steer),
            "note": note,
            "error": error,
        }
        return templates.TemplateResponse(request, "loop.html", context)

    @app.get("/loop/{repo_key}/{loop_id}/pulse", name="loop_pulse")
    def loop_pulse(repo_key: str, loop_id: str) -> JSONResponse:
        found = find_loop(config(), repo_key, loop_id)
        if found is None:
            raise HTTPException(404, "no such loop on this board")
        return JSONResponse({"pulse": pulse_of(found[0], loop_id, steer)})

    @app.get("/loop/{repo_key}/{loop_id}/file", response_class=HTMLResponse, name="loop_file")
    def loop_file(request: Request, repo_key: str, loop_id: str, path: str) -> Response:
        repo, manifest, view = view_of(repo_key, loop_id)
        target = inside(repo.path, path)
        size = target.stat().st_size
        body: Markup | None = None
        text = ""
        reason = ""
        if target.suffix.lower() not in TEXT_SUFFIXES:
            reason = "not shown: the board opens only text files it knows"
        elif size > MAX_FILE_BYTES:
            reason = f"{size // 1000} kB: too large to show here"
        else:
            try:
                text = target.read_text(encoding="utf-8")
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
        text: Annotated[str, Form()] = "",
        choice: Annotated[str, Form()] = "",
    ) -> Response:
        check_token(token)
        repo, _, view = view_of(repo_key, loop_id)
        asked = view.state.question if view.state else None
        picked = next((option for option in asked.options if option.id == choice), None) if asked else None
        if choice and picked is None:
            return back(repo_key, loop_id, error="Nothing was sent: that choice is no longer offered.")
        message = text.strip() or (picked.label if picked else "")
        if not message:
            return back(repo_key, loop_id, error="Nothing was sent: the reply was empty.")
        if len(message) > MAX_REPLY_CHARS:
            return back(repo_key, loop_id, error=f"Nothing was sent: over {MAX_REPLY_CHARS} characters.")
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
                key=board_key(),
                question=asked.id if asked else None,
                choice=picked.id if picked else None,
            )
        except StoreError as problem:
            return back(repo_key, loop_id, error=str(problem))
        return back(repo_key, loop_id, note="Sent. The loop reads it at its next round.")

    @app.post("/loop/{repo_key}/{loop_id}/stop", name="loop_stop")
    def loop_stop(repo_key: str, loop_id: str, token: Annotated[str, Form()]) -> Response:
        check_token(token)
        repo, _, view = view_of(repo_key, loop_id)
        if view.state and view.state.stop_requested:
            return back(repo_key, loop_id, note="A stop is already waiting for the loop.")
        try:
            store.append_inbox(repo.path, loop_id, "stop", key=board_key())
        except StoreError as problem:
            return back(repo_key, loop_id, error=str(problem))
        return back(repo_key, loop_id, note="Stop sent. The loop ends after its current round.")

    @app.post("/loop/{repo_key}/{loop_id}/start", name="loop_start")
    def loop_start(
        repo_key: str,
        loop_id: str,
        token: Annotated[str, Form()],
        command: Annotated[str, Form()] = "",
        confirm: Annotated[str, Form()] = "",
    ) -> Response:
        check_token(token)
        repo, manifest, _ = view_of(repo_key, loop_id)
        if command != manifest.commands.get("start", ""):
            # The loop rewrote its command after the page was drawn: run only what the person saw.
            return back(
                repo_key, loop_id, error="Not started: the start command changed. Check it and press again."
            )
        first = not steer.is_confirmed(repo, command)
        if first and confirm != "yes":
            return back(
                repo_key,
                loop_id,
                error="Not started: first start of this command. Read it, tick the box, press again.",
            )
        try:
            process = steer.start(repo, manifest)
        except StoreError as problem:
            return back(repo_key, loop_id, error=f"Not started: {problem}.")
        if first:
            steer.confirm(repo, command)
        return back(repo_key, loop_id, note=f"Started: {process.command} (pid {process.pid}).")

    @app.post("/loop/{repo_key}/{loop_id}/kill", name="loop_kill")
    def loop_kill(repo_key: str, loop_id: str, token: Annotated[str, Form()]) -> Response:
        check_token(token)
        repo, _, _ = view_of(repo_key, loop_id)
        try:
            steer.kill(repo, loop_id)
        except StoreError as problem:
            return back(repo_key, loop_id, error=f"{problem}.".capitalize())
        return back(repo_key, loop_id, note="The process was told to end.")

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


def inbox_marks(state: LoopState) -> dict[str, bool | None]:
    """For each inbox entry, whether this board signed it; None where the board has no key yet."""
    key = read_key()
    return {item.entry.id: is_signed(item.entry.body(), key, state.manifest.id) for item in state.inbox}


def pulse_of(repo: Repo, loop_id: str, steer: Runner) -> str:
    process = steer.process(repo, loop_id)
    alive = "1" if process and process.alive else "0"
    try:
        log_size = steer.log_path(repo, loop_id).stat().st_size
    except OSError:
        log_size = 0
    return f"{store.fingerprint(repo.path, loop_id)}.{alive}.{log_size}"


def serve(port: int) -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    hosts = frozenset({f"{HOST}:{port}", f"localhost:{port}"})
    uvicorn.run(create_app(allowed_hosts=hosts), host=HOST, port=port, log_level="warning")
