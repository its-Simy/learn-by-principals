"""The built web app (``web/dist``) served next to the API, so one port serves both.

Deep links such as ``/courses/CSE220`` are the SPA's routes, not files, so anything that isn't a
file under ``dist`` gets ``index.html``. ``/api/*`` never does: a mistyped API path answers 404
JSON, not a page the client would try to parse, and a known API path with the wrong method gets
the router's 405.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path, PureWindowsPath

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from starlette.routing import Match
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocketClose

DIST = Path(__file__).resolve().parents[1] / "web" / "dist"
# `mimetypes` reads the Windows registry, where .js is sometimes text/plain; a browser then
# refuses the bundle and the app is blank.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")


def outside_dist(path: str) -> bool:
    """A request path that could name something other than a file under dist, judged before
    ``resolve()`` touches it: on Windows a UNC path (``//host/share``) would make the server
    open an outbound SMB connection just by resolving it."""
    return (
        path.startswith("/")
        or "\\" in path
        or PureWindowsPath(path).is_absolute()
        or PureWindowsPath(path).drive != ""
        or ".." in path.split("/")
    )


NOT_BUILT = "The web app isn't built yet: run `pnpm --dir web build`, then reload.\n"
# index.html names the hashed bundles, so the browser must ask again after every build.
INDEX_HEADERS = {"Cache-Control": "no-cache"}


def _is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


class PageRoute(APIRoute):
    """The SPA's catch-all, which never claims an ``/api`` path. A known API path with the wrong
    method is then only a partial match for its own route (405), and an unknown one matches
    nothing and reaches ``no_api_route`` (404)."""

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if _is_api(scope.get("path", "")):
            return Match.NONE, {}
        return super().matches(scope)


async def no_api_route(scope: Scope, receive: Receive, send: Send) -> None:
    """The router's default: with ``PageRoute`` catching every other path, only ``/api`` paths
    (and websockets) get here."""
    if scope["type"] == "websocket":
        await WebSocketClose()(scope, receive, send)
        return
    raise HTTPException(404, f"No API route {scope['path']}")


def mount_web(app: FastAPI, dist: Path = DIST) -> None:
    """Call last: the catch-all must come after every API route."""
    dist = dist.resolve()
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    app.router.default = no_api_route

    def web(path: str) -> Response:
        index = dist / "index.html"
        if not index.is_file():
            return PlainTextResponse(NOT_BUILT)
        if outside_dist(path):
            raise HTTPException(404, "Not a file")
        try:
            file = (dist / path).resolve()
        except ValueError:  # e.g. an embedded NUL byte (/%00)
            raise HTTPException(404, "Not a file") from None
        if path and file.is_relative_to(dist) and file.is_file():
            if file == index:
                return FileResponse(index, headers=INDEX_HEADERS)
            return FileResponse(file)
        if path.startswith("assets/"):  # a missing bundle, not a page: index.html would be
            raise HTTPException(404, f"No file /{path}")  # parsed as JavaScript
        return FileResponse(index, headers=INDEX_HEADERS)

    app.router.add_api_route(
        "/{path:path}",
        web,
        methods=["GET"],
        include_in_schema=False,
        route_class_override=PageRoute,
    )
