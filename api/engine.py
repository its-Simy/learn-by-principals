"""The threads behind the web API.

Localhost only, no auth, one user: ``brightlearn web`` binds 127.0.0.1 and trusts whoever can
reach it, exactly as the CLI trusts whoever runs it.

Three things in core are not thread-safe: a ``GeminiNotebookProvider`` (a private asyncio loop
and pacing state), a ``Router`` (its in-process failure map) and a live ``Tutor``. Each gets one
owner thread. The ``interactive`` worker runs tutor sessions and grounded questions, one at a
time; the ``jobs`` worker runs long work (link, seed, exam create and grade, podcast), one at a
time. The two run side by side, and seed and exam create start fresh NotebookLM conversations on
the jobs worker, so P66 is kept by refusing, not by the threads: a session can't start while a
conversation job is active on its course (``Jobs.running``), and those jobs ``guard`` first.
Reads and DB-only writes don't come here: they use a per-request connection (``api/deps.db``),
so a list view never waits behind a five-minute tutor turn.
"""

from __future__ import annotations

import copy
import logging
import queue
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import Future, InvalidStateError
from dataclasses import dataclass
from typing import Any, Literal, TypeVar, get_args

from core import wiring
from core.config import Config, ensure_home
from core.ledger.ledger import utcnow
from core.memory.db import Courses, Manifest, connect
from core.memory.learner import LearnerMemory
from core.memory.vault import Vault
from core.providers.knowledge.base import KnowledgeProvider
from core.providers.models.base import ModelProvider
from core.router.router import Router
from core.tutor import Tutor

log = logging.getLogger(__name__)

T = TypeVar("T")

# Every model purpose a route can need: the tutor and exam generation teach, the Analyzer, the
# Critic and the grader analyse. Housekeeping (Ollama) has no route yet.
PURPOSES = ("teaching", "analysis")

# Every kind of job, in one place: the web client's types are generated from it (via JobOut).
JobKind = Literal["link", "seed", "exam_create", "exam_grade", "podcast"]
JOB_KINDS: frozenset[JobKind] = frozenset(get_args(JobKind))

# Jobs whose first NotebookLM query starts a fresh conversation, deleting the course's latest
# one, so they can't run while that course has a tutor session open (P66).
CONVERSATION_JOBS: frozenset[JobKind] = frozenset({"exam_create", "seed"})

JobStatus = Literal["queued", "running", "done", "failed"]
ACTIVE: frozenset[JobStatus] = frozenset({"queued", "running"})

# How long ``close`` waits for a worker to finish what it is running. Its thread is a daemon, so
# Ctrl-C mid-podcast exits after this rather than after the podcast, as it would in the CLI.
CLOSE_TIMEOUT_S = 2.0
MIN_JOIN_S = 0.2
SHUTTING_DOWN = "server shutting down"


@dataclass
class Resources:
    """What one worker thread owns. Nothing here is thread-safe, so nothing here is shared."""

    config: Config
    conn: sqlite3.Connection
    knowledge: KnowledgeProvider
    providers: dict[str, ModelProvider]

    @property
    def learner(self) -> LearnerMemory:
        return LearnerMemory(self.conn)

    @property
    def manifest(self) -> Manifest:
        return Manifest(self.conn)

    @property
    def courses(self) -> Courses:
        return Courses(self.conn)

    @property
    def vault(self) -> Vault:
        return Vault(self.config.vault_root)

    def router(self) -> Router:
        """A fresh router per task: a Router remembers provider failures for its own lifetime
        ("this process only"), and a failure an hour ago shouldn't skip a provider now. The
        cooldowns that matter live in ``provider_health`` and are read by every router."""
        return wiring.router(self.config, self.conn, self.providers)

    def close(self) -> None:
        try:
            close = getattr(self.knowledge, "close", None)
            if close is not None:
                close()
        finally:
            self.conn.close()


def open_resources(config: Config) -> Resources:
    """The real wiring. Runs on the worker's own thread, so the connection and NotebookLM's
    event loop are bound to the thread that will use them."""
    ensure_home(config)
    conn = connect(config.db_path)
    try:
        providers = wiring.model_providers(config, PURPOSES)
        knowledge = wiring.knowledge(config, conn)
    except BaseException:
        conn.close()
        raise
    return Resources(config, conn, knowledge, providers)


class Worker:
    """One daemon thread and its queue; every callable gets the thread's ``Resources``.

    A daemon thread rather than an executor so Ctrl-C on ``brightlearn web`` exits at once, even
    mid-podcast.
    """

    def __init__(
        self,
        name: str,
        config: Config,
        open_resources: Callable[[Config], Resources] = open_resources,
    ) -> None:
        self.name = name
        self._config = config
        self._open = open_resources
        self._queue: queue.Queue[tuple[Callable[[Resources], Any], Future[Any]] | None] = (
            queue.Queue()
        )
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running: Future[Any] | None = None  # the future of the callable now running
        self._closed = False

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError(f"the {self.name} worker is closed")
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name=f"brightlearn-{self.name}", daemon=True
                )
                self._thread.start()

    def submit(self, fn: Callable[[Resources], T]) -> Future[T]:
        future: Future[T] = Future()
        with self._lock:
            if self._closed or self._thread is None:
                state = "closed" if self._closed else "not started"
                raise RuntimeError(f"the {self.name} worker is {state}")
            self._queue.put((fn, future))
        return future

    def call(self, fn: Callable[[Resources], T]) -> T:
        """Run ``fn`` on the worker and wait; its exception is raised here."""
        return self.submit(fn).result()

    def close(self, timeout: float = CLOSE_TIMEOUT_S) -> None:
        """Cancel what hasn't started and give the running callable ``timeout`` to finish; the
        resources are closed on their own thread once it has. Safe to call twice.

        A callable still running after ``timeout`` goes on running on the daemon thread, but its
        future fails now: a request thread waiting in ``call`` is not a daemon, and would keep
        the process alive until, say, a five-minute tutor turn returned.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
            thread = self._thread
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is not None:
                    item[1].cancel()
            self._queue.put(None)
        if thread is None or thread is threading.current_thread():
            return  # never started, or closed by its own callable, which then finishes normally
        thread.join(timeout)
        with self._lock:
            running = self._running if thread.is_alive() else None
        if running is not None:
            log.warning("The %s worker is still busy; leaving it to exit with us", self.name)
            _settle(running.set_exception, RuntimeError(SHUTTING_DOWN))

    def _run(self) -> None:
        resources: Resources | None = None
        error: BaseException | None = None
        try:
            resources = self._open(self._config)
        except BaseException as exc:
            log.exception("The %s worker couldn't open its resources", self.name)
            error = exc
        try:
            while (item := self._queue.get()) is not None:
                fn, future = item
                if not future.set_running_or_notify_cancel():
                    continue
                if error is not None:
                    future.set_exception(error)
                    continue
                with self._lock:
                    self._running = future
                try:
                    outcome = fn(resources)
                except BaseException as exc:
                    _settle(future.set_exception, exc)
                else:
                    _settle(future.set_result, outcome)
                finally:
                    with self._lock:
                        self._running = None
        finally:
            if resources is not None:
                try:
                    resources.close()
                except Exception:
                    log.exception("Closing the %s worker's resources failed", self.name)


def _settle(set_outcome: Callable[[Any], None], value: Any) -> None:
    """Resolve a future that ``close`` may already have failed (``SHUTTING_DOWN``), or that
    finished just before ``close`` got to it."""
    try:
        set_outcome(value)
    except InvalidStateError:
        pass


@dataclass
class Job:
    id: str
    kind: JobKind
    course: str
    created_at: str
    status: JobStatus = "queued"
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None  # str(exc) only: the exception (e.g. SessionOpen) isn't copyable


class JobRunning(Exception):
    """A job of a conflicting kind is queued or running on this course."""

    def __init__(self, job: Job) -> None:
        self.job = job
        super().__init__(
            f"A {job.kind} job ({job.id}) is {job.status} on {job.course}; wait for it to finish."
        )


class Jobs:
    """In-memory registry over the jobs worker. Jobs are lost on restart; the files and rows
    they wrote are not. Every read returns a copy, so a caller never sees a job half-updated."""

    def __init__(self, worker: Worker, now: Callable[[], str] = utcnow) -> None:
        self.worker = worker
        self._now = now
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}

    def submit(
        self, kind: JobKind, course: str, fn: Callable[[Resources], dict[str, Any] | None]
    ) -> Job:
        """Queue ``fn``; its return value becomes the job's ``result``. A raised exception marks
        the job failed with the exception's message, since nobody is waiting to catch it."""
        if kind not in JOB_KINDS:
            raise ValueError(f"Unknown job kind {kind!r}; one of {sorted(JOB_KINDS)}")
        job = Job(uuid.uuid4().hex[:12], kind, course, self._now())

        def run(resources: Resources) -> None:
            self._update(job, status="running", started_at=self._now())
            try:
                result = fn(resources)
            except BaseException as exc:
                # BaseException too (e.g. asyncio.CancelledError out of NotebookLM's loop), or
                # the job would read "running" forever.
                log.exception("Job %s (%s on %s) failed", job.id, kind, course)
                error = str(exc) or type(exc).__name__
                self._update(job, error=error, finished_at=self._now(), status="failed")
                if not isinstance(exc, Exception):
                    raise  # cancellation or exit is for the worker to see, not just the job
            else:
                self._update(job, result=result, finished_at=self._now(), status="done")

        with self._lock:
            self._jobs[job.id] = job
        try:
            self.worker.submit(run)
        except RuntimeError:  # the worker is closed: the job will never run, so forget it
            with self._lock:
                del self._jobs[job.id]
            raise
        return self._copy(job)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return copy.copy(job) if job else None

    def all(self, course: str | None = None) -> list[Job]:
        """Oldest first: the order the worker runs them in."""
        with self._lock:
            return [
                copy.copy(j) for j in self._jobs.values() if course is None or j.course == course
            ]

    def running(self, course: str, kinds: Iterable[str]) -> Job | None:
        """A queued or running job of one of ``kinds`` on ``course``. Queued counts: a job is
        visible here from the moment ``submit`` returns, which is what lets BL-045 check and
        then register under one lock with no window where neither side sees the other."""
        kinds = frozenset(kinds)
        with self._lock:
            for job in self._jobs.values():
                if job.course == course and job.kind in kinds and job.status in ACTIVE:
                    return copy.copy(job)
        return None

    def _update(self, job: Job, **changes: Any) -> None:
        with self._lock:
            for name, value in changes.items():
                setattr(job, name, value)

    def _copy(self, job: Job) -> Job:
        with self._lock:
            return copy.copy(job)


class Engine:
    """The two workers, the job registry and the live tutors of one server process."""

    def __init__(
        self,
        config: Config,
        open_resources: Callable[[Config], Resources] = open_resources,
    ) -> None:
        self.config = config
        self.interactive = Worker("interactive", config, open_resources)
        self.jobs = Jobs(Worker("jobs", config, open_resources))
        # Touched only on the interactive worker; other threads read copies (live_sessions).
        self.tutors: dict[str, Tutor] = {}
        # Held over "check, then register" (a session start, a no-session ask, a conversation
        # job's submit, an upload's import), so one side can't slip past the other's check (P66).
        # Never held while waiting on a worker: a callable on that worker may need it.
        self.lock = threading.Lock()

    def start(self) -> None:
        """Start each worker and wait for it to open its resources, so a bad ``[routing]`` or an
        unreadable database fails the server's startup, as it fails a CLI command. One at a time:
        the first open migrates the database, and two migrations at once would collide."""
        try:
            for worker in (self.interactive, self.jobs.worker):
                worker.start()
                worker.call(lambda r: None)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        for course, tutor in list(self.tutors.items()):
            if tutor.row is not None and not tutor.ended:
                log.warning(
                    "Tutor session %s on %s left open; `brightlearn sessions close` ends it",
                    tutor.row.session_id,
                    course,
                )
        self.tutors.clear()
        # One wait for both, not one each; an idle worker still gets the moment it needs to
        # take its stop marker and close its resources.
        deadline = time.monotonic() + CLOSE_TIMEOUT_S
        for worker in (self.interactive, self.jobs.worker):
            worker.close(max(MIN_JOIN_S, deadline - time.monotonic()))

    def live_sessions(self) -> dict[str, str]:
        """``{course: session_id}`` of the tutors this process holds, for list views."""
        return {
            course: tutor.row.session_id
            for course, tutor in list(self.tutors.items())
            if tutor.row is not None and not tutor.ended
        }

    def drain(self) -> None:
        """Wait until every job queued so far has run (the worker is FIFO). For tests."""
        self.jobs.worker.call(lambda r: None)
