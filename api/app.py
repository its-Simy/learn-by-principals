"""The FastAPI app behind ``brightlearn web``: localhost only, no auth, one user.

Binding 127.0.0.1 keeps other machines out, not other web pages: any page the user visits can
send requests to it. A DNS-rebinding page reaches it under its own host name with same-origin
access, and a form post, an empty-body POST or a multipart upload is a CORS "simple" request
that arrives without a preflight. So the Host header must name 127.0.0.1 or localhost (400
otherwise), and a write must come from our own pages (403 otherwise; ``write_allowed``).

Building the app has no side effects; the engine's workers start in the lifespan, only under a
server, so ``create_app(config).openapi()`` is safe anywhere (``brightlearn dev openapi``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from api.engine import Engine, JobRunning
from api.routes import system
from api.static import mount_web
from core.config import Config, load_config
from core.exams.grade import GradeError
from core.exams.paper import ExamFileError
from core.exams.spec import SpecError
from core.memory.db import DuplicateCourse
from core.memory.learner import LearnerError
from core.memory.seeding import SeedingError
from core.personas import PersonaError
from core.providers.knowledge.base import KnowledgeError
from core.providers.models.base import ModelError, ModelRateLimited
from core.providers.storage.base import StorageError
from core.sessions import SessionOpen

ROUTERS = (system.router,)

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# The learner asked for something core refuses (a bad spec, an unknown bucket, ...): their input
# to fix, not a server fault. ValueError covers ImportRefused and CourseError.
UNPROCESSABLE: tuple[type[Exception], ...] = (
    LearnerError,
    SeedingError,
    SpecError,
    ExamFileError,
    GradeError,
    PersonaError,
    StorageError,
    ValueError,
)


def create_app(config: Config | None = None, engine: Engine | None = None) -> FastAPI:
    config = config or load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine.start()
        try:
            yield
        finally:
            app.state.engine.close()

    app = FastAPI(title="BrightLearn", version="0.1.0", lifespan=lifespan)
    app.state.config = config
    app.state.engine = engine or Engine(config)
    protect(app)
    for router in ROUTERS:
        app.include_router(router, prefix="/api")
    register_errors(app)
    mount_web(app)
    return app


def protect(app: FastAPI) -> None:
    """Refuse requests a browser sent on behalf of another site (see the module docstring)."""
    app.add_middleware(SameOriginWrites)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)  # added last: first


def write_allowed(fetch_site: str | None, origin: str | None) -> bool:
    """A browser names the requesting site in ``Sec-Fetch-Site`` (and on writes in ``Origin``);
    ours is same-origin, or a localhost origin such as the Vite dev server. A request with
    neither header isn't from a browser page (curl, a script, the tests), so it may write."""
    if fetch_site in ("same-origin", "none"):
        return True
    if origin is not None:
        return _local_origin(origin)
    return fetch_site is None


def _local_origin(origin: str) -> bool:
    try:
        parts = urlsplit(origin)
        return parts.scheme in ("http", "https") and parts.hostname in ALLOWED_HOSTS
    except ValueError:  # e.g. an unclosed IPv6 bracket
        return False


class SameOriginWrites:
    """403 for a POST, PUT, PATCH or DELETE that ``write_allowed`` refuses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in UNSAFE_METHODS:
            headers = Headers(scope=scope)
            if not write_allowed(headers.get("sec-fetch-site"), headers.get("origin")):
                detail = "Refused: this request came from another site's page"
                response = JSONResponse({"code": "cross_origin", "detail": detail}, 403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def register_errors(app: FastAPI) -> None:
    """Core's exceptions as HTTP answers the web app can act on. Every 409 carries a ``code``
    so the UI can offer the way out in place (close the stale session, wait for the job)."""

    async def duplicate_course(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"code": "duplicate_course", "detail": str(exc)}, status_code=409)

    async def session_open(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, SessionOpen)
        body = {
            "code": "session_open",
            "detail": str(exc),
            "session_id": exc.session.session_id,
            "stale": exc.stale,
        }
        return JSONResponse(body, status_code=409)

    async def job_running(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, JobRunning)
        body = {
            "code": "job_running",
            "detail": str(exc),
            "job_id": exc.job.id,
            "kind": exc.job.kind,
        }
        return JSONResponse(body, status_code=409)

    async def unprocessable(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    async def upstream(request: Request, exc: Exception) -> JSONResponse:
        """A provider failed: say which one and, for a rate limit, when to retry."""
        provider = None  # NoProvider names none: no provider was tried
        if isinstance(exc, KnowledgeError):
            provider = "notebooklm"
        elif isinstance(exc, ModelError):
            provider = exc.provider
        hint = exc.hint if isinstance(exc, ModelRateLimited) else None
        body = {
            "detail": str(exc),
            "provider": provider,
            "resets_at": hint.resets_at if hint else None,
        }
        return JSONResponse(body, status_code=502)

    async def not_found(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    # Starlette picks a handler by the exception's MRO, so DuplicateCourse (a ValueError) gets
    # its 409 rather than the 422 whatever the order; it comes first so the code reads that way.
    app.add_exception_handler(DuplicateCourse, duplicate_course)
    app.add_exception_handler(SessionOpen, session_open)
    app.add_exception_handler(JobRunning, job_running)
    for cls in UNPROCESSABLE:
        app.add_exception_handler(cls, unprocessable)
    app.add_exception_handler(KnowledgeError, upstream)
    app.add_exception_handler(ModelError, upstream)  # NoProvider is a ModelError
    app.add_exception_handler(FileNotFoundError, not_found)
