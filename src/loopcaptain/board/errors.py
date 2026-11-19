"""What the board answers when a request cannot be served: a page with the reason and a way back.

A browser that asked for a page gets `error.html`; a script that fetched (the reload pulse) gets
the same words as JSON. Either way the status code says what happened.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException

from loopcaptain.board.discover import reason
from loopcaptain.protocol.store import StoreError

log = logging.getLogger("loopcaptain.web")

UNREADABLE = 503
INCOMPLETE = 422
FAULT = 500
#: The heading for each status the board answers with; anything else gets the last one.
TITLES = {
    404: "Not on this board",
    405: "Not a way to ask for this page",
    INCOMPLETE: "Nothing was sent: the form was incomplete",
    UNREADABLE: "The board cannot read what it needs",
    FAULT: "The board ran into a fault",
}
OTHER_TITLE = "The board could not do that"
#: A page asked for with a value in its address that cannot be read: no form was sent.
BAD_ADDRESS_TITLE = "This address cannot be read"

#: Everything the pages load comes from this server: no inline script or style, no other origin.
CONTENT_POLICY = (
    "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
#: What every answer of the board carries.
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def secured(response: Response) -> Response:
    """The response with the board's headers. A fault's answer is sent past the board's middleware,
    by the server's outermost layer, so its handler sets them itself."""
    response.headers.update(SECURITY_HEADERS)
    return response


def wants_page(request: Request) -> bool:
    """Whether a browser asked for a page; a fetch from the page's script sends no such header."""
    return "text/html" in request.headers.get("accept", "")


def error_response(
    templates: Jinja2Templates, request: Request, status: int, message: str, title: str = ""
) -> Response:
    if not wants_page(request):
        return JSONResponse({"detail": message}, status_code=status)
    params = request.path_params
    loop = (
        str(request.url_for("loop_page", repo_key=params["repo_key"], loop_id=params["loop_id"]))
        if {"repo_key", "loop_id"} <= params.keys()
        else ""
    )
    context = {
        "title": title or TITLES.get(status, OTHER_TITLE),
        "message": message,
        "loop_url": loop if loop != str(request.url).split("?")[0] else "",
    }
    return templates.TemplateResponse(request, "error.html", context, status_code=status)


def add_error_pages(app: FastAPI, templates: Jinja2Templates) -> None:
    """One place for every refusal and fault: the board's own page instead of a bare JSON line."""

    @app.exception_handler(HTTPException)
    def refused(request: Request, problem: HTTPException) -> Response:
        return error_response(templates, request, problem.status_code, str(problem.detail))

    @app.exception_handler(RequestValidationError)
    def incomplete(request: Request, problem: RequestValidationError) -> Response:
        missing = ", ".join(str(item["loc"][-1]) for item in problem.errors()[:3])
        if request.method in ("GET", "HEAD"):
            message = (
                f"The address holds a value the board cannot read: {missing}. Open the page from a link."
            )
            return error_response(templates, request, INCOMPLETE, message, BAD_ADDRESS_TITLE)
        message = f"The request lacked or misnamed: {missing}. Go back, reload the page and send again."
        return error_response(templates, request, INCOMPLETE, message)

    @app.exception_handler(StoreError)
    def cannot_read(request: Request, problem: StoreError) -> Response:
        """The board's own config or a loop's folder cannot be read."""
        return error_response(templates, request, UNREADABLE, str(problem))

    @app.exception_handler(Exception)
    def fault(request: Request, problem: Exception) -> Response:
        log.error("fault on %s %s: %s", request.method, request.url.path, reason(problem))
        message = f"{reason(problem)}. The terminal where the board runs has the details."
        return secured(error_response(templates, request, FAULT, message))
