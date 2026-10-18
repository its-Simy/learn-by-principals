"""Chat: the live tutor session, grounded questions, and a course's past sessions.

A course's tutor lives in ``engine.tutors`` and is only touched on the interactive worker, which
also runs every grounded ask, one at a time. P66 (one live NotebookLM conversation per course)
across the two workers: a session start holds ``engine.lock`` over the guard, the conversation-job
check and the registry insert, so no seed or exam job can be submitted in between, and a
no-session ask refuses while such a job is queued or running, because the jobs worker's own
provider would interleave a second fresh conversation on the same notebook. The other way round,
the ask marks its course in ``engine.asking`` until its query returns, and the seed and exam
routes refuse while it is there (P100).

Only the link job creates a course's notebook, so a start or an ask on a course with no notebook
and nothing linked is a 422 ``nothing_linked`` rather than a second ``ensure_notebook`` racing
the first.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from api.deps import ConfigDep, CourseDep, DbDep, EngineDep
from api.engine import CONVERSATION_JOBS, Engine, JobRunning, Resources
from api.errors import (
    CONVERSATION_JOB,
    SESSION_LIVE,
    SESSION_OPEN,
    Conflict,
    Refused,
    conflicts,
)
from api.schemas.chat import (
    AskIn,
    AskOut,
    LiveSessionOut,
    SessionOut,
    SessionStartIn,
    TurnIn,
    TurnOut,
)
from api.schemas.system import TextOut
from core import wiring
from core.memory.db import ResourceRow
from core.memory.learner import LearnerMemory
from core.memory.vault import Vault
from core.sessions import guard, state
from core.tutor import Tutor

router = APIRouter(tags=["chat"])


# -- the live session (interactive worker) ----------------------------------------------------


@router.post("/courses/{course}/session", responses=conflicts(SESSION_OPEN, CONVERSATION_JOB))
def start_session(
    course: CourseDep, engine: EngineDep, body: SessionStartIn | None = None
) -> LiveSessionOut:
    """409 ``session_open`` while any session is open on the course (this server's, a CLI one,
    or a stale one to close), 409 ``job_running`` during a seed or exam-create job."""
    persona = (body or SessionStartIn()).persona

    def start(r: Resources) -> LiveSessionOut:
        _linked(r, course)
        with engine.lock:
            guard(r.learner, course)
            _refuse_conversation_jobs(engine, course)
            tutor = wiring.tutor(r.config, r.conn, r.knowledge, r.providers, course, persona)
            tutor.start()
            engine.tutors[course] = tutor
        # The first Challenger probe is a model call: not under the lock. The session's row and
        # registry entry already keep every other conversation off the course.
        tutor.opening()
        return LiveSessionOut.from_core(tutor)

    return engine.interactive.call(start)


@router.get("/courses/{course}/session")
def get_session(course: CourseDep, engine: EngineDep) -> LiveSessionOut | None:
    """The live session, or null; on the interactive worker, the only thread that touches a
    tutor."""

    def get(r: Resources) -> LiveSessionOut | None:
        tutor = engine.tutors.get(course)
        if tutor is None or tutor.ended:
            return None
        return LiveSessionOut.from_core(tutor)

    return engine.interactive.call(get)


@router.post("/courses/{course}/session/turn")
def turn(course: CourseDep, body: TurnIn, engine: EngineDep) -> TurnOut:
    """One REPL line, exactly as ``brightlearn tutor`` reads it; ``/end`` ends the session.
    A line the tutor couldn't answer is still a 200, with ``error`` saying why. A typed
    ``/ask q`` answers as the CLI's does, its citations listed in ``reply``; ``POST ask`` gives
    them as data."""
    text = body.text

    def run(r: Resources) -> TurnOut:
        tutor = _live(engine, course)
        assert tutor.session is not None  # started before it was registered
        exchanges = len(tutor.session.turns)
        try:
            reply = tutor.handle(text)
        finally:
            _forget_if_ended(engine, course, tutor)
        answered = len(tutor.session.turns) > exchanges
        return TurnOut.from_core(tutor, reply, answered, tutor.last_error)

    return engine.interactive.call(run)


@router.post("/courses/{course}/session/end")
def end_session(course: CourseDep, engine: EngineDep) -> TurnOut:
    """Ends the session and runs the Analyzer on its transcript, which can take minutes."""

    def run(r: Resources) -> TurnOut:
        tutor = _live(engine, course)
        try:
            reply = tutor.end()
        finally:
            _forget_if_ended(engine, course, tutor)
        return TurnOut.from_core(tutor, reply)

    return engine.interactive.call(run)


@router.post("/courses/{course}/ask", responses=conflicts(SESSION_OPEN, CONVERSATION_JOB))
def ask(course: CourseDep, body: AskIn, engine: EngineDep) -> AskOut:
    """Inside a live session, the tutor's ``/ask`` in the session's own conversation. Otherwise a
    fresh conversation, which deletes the course's latest one, so only when no session is open
    and no seed or exam job is about to start one; and none can be submitted until it returns."""
    question, source_ids = body.question, body.source_ids

    def run(r: Resources) -> AskOut:
        tutor = engine.tutors.get(course)
        if tutor is not None and not tutor.ended:
            if source_ids is not None:
                raise ValueError(
                    "source_ids can't be used inside a live session: its /ask asks every "
                    "source, in the session's conversation"
                )
            answer = tutor.ground_answer(question)  # NotebookLM failing is a 502, as below
            return AskOut.from_core(answer, _sources(r, course), in_session=True)
        sources = _linked(r, course)
        with engine.lock:
            guard(r.learner, course)
            _refuse_conversation_jobs(engine, course)
            engine.asking.add(course)
        try:  # the query runs without the lock; the mark keeps seed and exam create off (P100)
            if source_ids is not None:
                unknown = sorted(set(source_ids) - set(sources))
                if not source_ids or unknown:
                    raise ValueError(
                        f"source_ids must name NotebookLM sources of {course}"
                        + (f"; not linked: {', '.join(unknown)}" if unknown else "")
                    )
            notebook_id = r.knowledge.ensure_notebook(course)
            answer = r.knowledge.query(notebook_id, question, source_ids)
        finally:
            # Taken again on this worker's thread: no lock holder ever waits on this worker.
            with engine.lock:
                engine.asking.discard(course)
        return AskOut.from_core(answer, sources)

    return engine.interactive.call(run)


def _sources(r: Resources, course: str) -> dict[str, ResourceRow]:
    """The course's linked rows by NotebookLM source id, to label citations with."""
    return {row.notebook_source_id: row for row in r.manifest.all(course) if row.notebook_source_id}


def _linked(r: Resources, course: str) -> dict[str, ResourceRow]:
    """``_sources``, refused (422 ``nothing_linked``) only when there are none and the course has
    no notebook yet: replacing a changed file, the link job clears its ``notebook_source_id``
    before adding it again, so a course whose one file is mid-replace has no linked row for a
    moment, but its notebook is there and ``ensure_notebook`` only reads it."""
    rows = _sources(r, course)
    if not rows and not _has_notebook(r, course):
        raise Refused(
            "nothing_linked",
            f"Nothing from {course} is in NotebookLM yet; upload a file and let its link job "
            "finish (or retry it).",
        )
    return rows


def _has_notebook(r: Resources, course: str) -> bool:
    """The knowledge provider records each course's notebook in ``notebooks`` when it makes one
    (``ensure_notebook``), and reads it back from there."""
    found = r.conn.execute("SELECT 1 FROM notebooks WHERE course = ?", (course,)).fetchone()
    return found is not None


def _refuse_conversation_jobs(engine: Engine, course: str) -> None:
    job = engine.jobs.running(course, CONVERSATION_JOBS)
    if job is not None:
        raise JobRunning(job)


def _live(engine: Engine, course: str) -> Tutor:
    tutor = engine.tutors.get(course)
    if tutor is None or tutor.ended:
        raise HTTPException(404, f"No live tutor session on {course}; start one")
    return tutor


def _forget_if_ended(engine: Engine, course: str, tutor: Tutor) -> None:
    """Also when ``end`` raised after marking the row ended (the Analyzer failed): the session
    is over either way, and an ended tutor must not hold the course."""
    if tutor.ended and engine.tutors.get(course) is tutor:
        del engine.tutors[course]


# -- past sessions (the request's own connection) ---------------------------------------------


@router.get("/courses/{course}/sessions")
def list_sessions(course: CourseDep, conn: DbDep, engine: EngineDep) -> list[SessionOut]:
    """Newest first."""
    live = set(engine.live_sessions().values())
    now = datetime.now(UTC)
    return [
        SessionOut.from_core(row, state(row, now), row.session_id in live)
        for row in LearnerMemory(conn).sessions(course)
    ]


@router.get("/sessions/{session_id}/transcript")
def transcript(session_id: str, conn: DbDep, cfg: ConfigDep) -> TextOut:
    """The Markdown transcript, also after ``maintain`` has archived it. Only ids with a row are
    looked up, so the id can't name another file."""
    if LearnerMemory(conn).get_session(session_id) is None:
        raise HTTPException(404, f"No session {session_id}")
    path = Vault(cfg.vault_root).session_transcript_path(session_id)
    for candidate in (path, path.parent / "archive" / path.name):
        if candidate.is_file():
            return TextOut(text=candidate.read_text(encoding="utf-8"))
    raise HTTPException(404, f"No transcript for session {session_id}")


@router.post("/sessions/{session_id}/close", responses=conflicts(SESSION_LIVE))
def close_session(session_id: str, conn: DbDep, engine: EngineDep) -> SessionOut:
    """Marks a session ended without running the Analyzer, as ``brightlearn sessions close``
    does: for one whose tutor is gone (a crash, a restart, a CLI session). This server's live
    session is a 409 ``session_live``: end it instead, which runs the Analyzer. Checked and
    closed under the lock a session start holds from writing its row to registering its tutor,
    so a session that is starting can't be closed before it shows as live."""
    learner = LearnerMemory(conn)
    with engine.lock:
        if session_id in engine.live_sessions().values():
            detail = f"Session {session_id} is live in this server; end it instead"
            raise Conflict("session_live", detail, session_id=session_id)
        if learner.get_session(session_id) is None:
            raise HTTPException(404, f"No session {session_id}")
        row = learner.close_session(session_id)  # already ended: LearnerError, a 422
    return SessionOut.from_core(row, state(row), live=False)
