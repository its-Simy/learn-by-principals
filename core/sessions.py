"""One live NotebookLM conversation per course (P66).

A tutor session owns its course's conversation until it ends, and starting a fresh one deletes
the latest, so anything else that would start one on that course must refuse while a session is
open. The rule lives here so the CLI and the API refuse identically; each words it for its own
user.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.maintenance import STALE_AFTER
from core.memory.learner import LearnerMemory, SessionRow, idle_for


class SessionOpen(Exception):
    """``stale`` is set when the session has had no turn for ``STALE_AFTER``, so a caller can
    suggest closing it instead of only waiting for it to end."""

    def __init__(self, session: SessionRow, stale: bool) -> None:
        self.session = session
        self.stale = stale
        message = (
            f"Tutor session {session.session_id} is open on {session.course} (started "
            f"{session.started_at}); NotebookLM keeps one live conversation per course."
        )
        if stale:
            message += " It looks stale; close it if it's finished or crashed."
        super().__init__(message)


def guard(learner: LearnerMemory, course: str, now: datetime | None = None) -> None:
    """Raise ``SessionOpen`` when ``course`` has an open tutor session; return otherwise."""
    open_rows = learner.open_sessions(course)
    if not open_rows:
        return
    session = open_rows[0]
    idle = idle_for(session, now or datetime.now(UTC))
    raise SessionOpen(session, idle > STALE_AFTER)
