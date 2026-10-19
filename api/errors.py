"""The 409s and 422s a route raises itself, how routes declare their 409s in the OpenAPI
document, and how a provider's failure is described to the UI.

``refuse_while_asking`` is here because two routers share it (seed and exam create).

Every 409 this API sends carries a ``code`` and a ``detail``, so the UI can offer the way out in
place. Core's own refusals (``SessionOpen``, ``JobRunning``, ``DuplicateCourse``) get theirs in
``api/app.py: register_errors``; a refusal that only the API makes raises ``Conflict``. A 422 is
``{detail}``, except the ones the UI acts on by kind: a route raises those as ``Refused``, so
they carry a ``code`` too and nothing has to match the sentence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.providers.knowledge.base import KnowledgeError
from core.providers.models.base import ModelError, ModelRateLimited

if TYPE_CHECKING:
    from api.engine import Engine


class Conflict(Exception):
    """A 409 ``{code, detail, **extra}``."""

    def __init__(self, code: str, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.extra = extra

    def body(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail, **self.extra}


class Refused(Exception):
    """A 422 ``{code, detail}``: input to change, of a kind the UI handles in place
    (``nothing_linked``: upload a file first; ``invalid_course_code``, ``invalid_term``: the
    field to fix)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail

    def body(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail}


def provider_failure(exc: Exception) -> dict[str, Any]:
    """``{provider, detail, resets_at}`` for a provider's failure: the 502 body, and a tutor
    turn's ``error``. ``provider`` is None for ``NoProvider`` (none was tried) and for anything
    that isn't a provider's error; ``resets_at`` is a rate-limit hint's text (e.g. ``3pm``)."""
    provider = None
    if isinstance(exc, KnowledgeError):
        provider = "notebooklm"
    elif isinstance(exc, ModelError):
        provider = exc.provider
    hint = exc.hint if isinstance(exc, ModelRateLimited) else None
    return {"provider": provider, "detail": str(exc), "resets_at": hint.resets_at if hint else None}


# What each code means, for a route's ``responses``. The bodies carry ``code`` and ``detail``;
# the extra fields are named here.
SESSION_OPEN = "a tutor session is open on the course (`session_open`; `session_id`, `stale`)"
CONVERSATION_JOB = (
    "a seed or exam-create job is queued or running on the course (`job_running`; `job_id`, `kind`)"
)
LINK_JOB = "a link job is queued or running on the course (`job_running`; `job_id`, `kind`)"
GRADE_JOB = "a grade job is queued or running on the course (`job_running`; `job_id`, `kind`)"
ASK_RUNNING = "a question to the course's sources is being answered (`ask_running`)"
DUPLICATE_COURSE = "the course already exists (`duplicate_course`)"
SESSION_LIVE = "the session is live in this server: end it instead (`session_live`; `session_id`)"
NO_OPEN_ATTEMPT = "the exam has no unfinished attempt (`no_open_attempt`)"


def conflicts(*reasons: str) -> dict[int | str, dict[str, Any]]:
    """A route's ``responses`` entry naming each 409 it can send."""
    text = "; or ".join(reasons)
    return {409: {"description": text[0].upper() + text[1:]}}


def refuse_while_asking(engine: Engine, course: str) -> None:
    """For the seed and exam-create routes, under ``engine.lock``: their job's fresh NotebookLM
    conversation would delete the one a no-session ask is being answered in (P100)."""
    if course in engine.asking:
        raise Conflict(
            "ask_running",
            f"A question to {course}'s sources is being answered; try again once it has been.",
        )
