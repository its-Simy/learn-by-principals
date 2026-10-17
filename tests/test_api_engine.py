"""BL-044: the API's worker threads, job registry and engine lifecycle."""

import dataclasses
import threading
import time
from types import SimpleNamespace

import pytest

from api.engine import CONVERSATION_JOBS, Engine, Resources, open_resources
from core.config import Config
from core.memory.db import connect
from core.sessions import guard
from tests.fakes.fake_knowledge import FakeKnowledge
from tests.fakes.fake_models import FakeModel


@pytest.fixture
def opened() -> list[tuple[int, Resources]]:
    return []


@pytest.fixture
def engine(config, opened):
    """An engine on fakes that records which thread opened each worker's resources."""
    kp = FakeKnowledge()
    models = {"claude": FakeModel("claude"), "codex": FakeModel("codex")}

    def fake_resources(cfg: Config) -> Resources:
        r = Resources(cfg, connect(cfg.db_path), kp, dict(models))
        opened.append((threading.get_ident(), r))
        return r

    engine = Engine(config, open_resources=fake_resources)
    engine.start()
    yield engine
    engine.close()


def test_each_worker_runs_everything_on_the_thread_that_opened_it(engine, opened):
    def where(r: Resources) -> tuple[int, int]:
        r.conn.execute("SELECT 1")  # sqlite3 refuses a connection opened on another thread
        return threading.get_ident(), id(r)

    interactive = {engine.interactive.call(where) for _ in range(5)}
    calls = [engine.jobs.worker.submit(where) for _ in range(5)]
    jobs = [engine.jobs.submit("link", "CSE220", lambda r: {"at": where(r)}) for _ in range(3)]
    engine.drain()
    on_jobs = {f.result() for f in calls} | {engine.jobs.get(j.id).result["at"] for j in jobs}

    assert len(interactive) == 1 and len(on_jobs) == 1
    # Each worker's thread is the one that opened its resources, and the two differ.
    assert interactive | on_jobs == {(ident, id(r)) for ident, r in opened}
    assert len(interactive | on_jobs) == 2


def test_a_failed_job_carries_its_message(engine):
    def needs_no_session(r: Resources) -> dict:
        r.learner.start_session("CSE220")
        guard(r.learner, "CSE220")  # raises SessionOpen, which can't be copied: str only
        return {"never": True}

    failed = engine.jobs.submit("exam_create", "CSE220", needs_no_session)
    done = engine.jobs.submit("link", "CSE220", lambda r: {"linked": 2})
    engine.drain()

    job = engine.jobs.get(failed.id)
    assert job.status == "failed" and job.result is None
    assert "Tutor session" in job.error and "is open on CSE220" in job.error
    assert job.started_at and job.finished_at
    assert engine.jobs.get(done.id).status == "done"
    assert engine.jobs.get(done.id).result == {"linked": 2}


def test_drain_returns_after_every_queued_job(engine):
    ran: list[int] = []

    def slow(n: int):
        def run(r: Resources) -> None:
            time.sleep(0.02)
            ran.append(n)

        return run

    submitted = [engine.jobs.submit("podcast", "CSE220", slow(n)) for n in range(3)]
    assert {j.status for j in submitted} <= {"queued", "running"}
    engine.drain()
    assert ran == [0, 1, 2]
    assert [j.status for j in engine.jobs.all("CSE220")] == ["done"] * 3
    assert engine.jobs.all("OTHER") == []


def test_running_sees_a_job_parked_on_an_event(engine):
    started, release = threading.Event(), threading.Event()

    def parked(r: Resources) -> None:
        started.set()
        release.wait(5)

    job = engine.jobs.submit("seed", "CSE220", parked)
    queued = engine.jobs.submit("exam_create", "CSE221", lambda r: None)
    assert started.wait(5)

    running = engine.jobs.running("CSE220", CONVERSATION_JOBS)
    assert running is not None and running.id == job.id and running.status == "running"
    assert engine.jobs.running("CSE221", CONVERSATION_JOBS).id == queued.id  # queued counts
    assert engine.jobs.running("CSE220", {"link"}) is None
    assert engine.jobs.running("OTHER", CONVERSATION_JOBS) is None

    release.set()
    engine.drain()
    assert engine.jobs.running("CSE220", CONVERSATION_JOBS) is None
    assert engine.jobs.running("CSE221", CONVERSATION_JOBS) is None


def test_reads_are_copies(engine):
    job = engine.jobs.submit("link", "CSE220", lambda r: None)
    engine.drain()
    copy = engine.jobs.get(job.id)
    copy.status = "failed"
    assert engine.jobs.get(job.id).status == "done"


class Interrupted(BaseException):
    """Like asyncio.CancelledError: not an Exception."""


def test_a_job_ended_by_a_base_exception_is_failed_not_running(engine):
    def cancelled(r: Resources) -> None:
        raise Interrupted("cancelled mid-upload")

    job = engine.jobs.submit("link", "CSE220", cancelled)
    later = engine.jobs.submit("link", "CSE220", lambda r: {"linked": 1})
    engine.drain()
    assert engine.jobs.get(job.id).status == "failed"
    assert engine.jobs.get(job.id).error == "cancelled mid-upload"
    assert engine.jobs.get(later.id).status == "done"  # the worker carried on


def test_an_unknown_job_kind_is_refused(engine):
    with pytest.raises(ValueError, match="Unknown job kind 'reindex'"):
        engine.jobs.submit("reindex", "CSE220", lambda r: None)
    assert engine.jobs.all() == []


def test_close_fails_a_call_that_outlives_the_timeout(engine):
    """Ctrl-C mid tutor turn: the request thread waiting in call() must not keep us alive."""
    started, release = threading.Event(), threading.Event()
    outcome: list[BaseException | str] = []

    def turn(r: Resources) -> str:
        started.set()
        release.wait(30)
        return "reply"

    def request() -> None:
        try:
            outcome.append(engine.interactive.call(turn))
        except BaseException as exc:
            outcome.append(exc)

    waiting = threading.Thread(target=request)
    waiting.start()
    assert started.wait(5)

    t0 = time.monotonic()
    engine.interactive.close(timeout=0.1)
    assert time.monotonic() - t0 < 1
    waiting.join(2)
    assert not waiting.is_alive()
    assert isinstance(outcome[0], RuntimeError) and str(outcome[0]) == "server shutting down"

    release.set()  # the turn finishes late; its result has nowhere to go and is dropped
    engine.interactive._thread.join(2)
    assert not engine.interactive._thread.is_alive()


def test_a_callable_may_close_its_own_worker(engine):
    assert engine.interactive.call(lambda r: engine.interactive.close()) is None
    engine.interactive._thread.join(2)
    assert not engine.interactive._thread.is_alive()
    with pytest.raises(RuntimeError, match="closed"):
        engine.interactive.submit(lambda r: None)


def test_a_failed_open_on_the_jobs_worker_closes_the_interactive_one(config):
    opened: list[Resources] = []

    class Tracked(Resources):
        closed = False

        def close(self) -> None:
            self.closed = True
            super().close()

    def second_fails(cfg: Config) -> Resources:
        if opened:
            raise ValueError("Unknown model provider 'gpt'")
        opened.append(Tracked(cfg, connect(cfg.db_path), FakeKnowledge(), {}))
        return opened[0]

    engine = Engine(config, open_resources=second_fails)
    with pytest.raises(ValueError, match="gpt"):
        engine.start()
    engine.interactive._thread.join(2)
    assert opened[0].closed and not engine.interactive._thread.is_alive()
    with pytest.raises(RuntimeError, match="closed"):
        engine.interactive.submit(lambda r: None)


def test_close_is_idempotent_and_refuses_new_work(config, engine):
    engine.close()
    engine.close()
    with pytest.raises(RuntimeError, match="closed"):
        engine.interactive.submit(lambda r: None)
    with pytest.raises(RuntimeError, match="closed"):
        engine.jobs.submit("link", "CSE220", lambda r: None)
    assert engine.jobs.all() == []  # a job that can never run isn't listed
    Engine(config).close()  # never started: nothing to stop


def test_live_sessions_lists_the_open_tutors(engine):
    def tutor(session_id: str, ended: bool = False) -> SimpleNamespace:
        return SimpleNamespace(row=SimpleNamespace(session_id=session_id), ended=ended)

    engine.tutors.update({"CSE220": tutor("s1"), "CSE221": tutor("s2", ended=True)})
    assert engine.live_sessions() == {"CSE220": "s1"}


def test_every_router_is_fresh(engine):
    first, second = engine.interactive.call(lambda r: (r.router(), r.router()))
    assert first is not second and set(first.providers) == {"claude", "codex"}


def test_a_bad_routing_fails_at_start(config, monkeypatch, tmp_path):
    """The real wiring, with no network: an unknown provider name stops the server starting."""
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(tmp_path / "nlm"))  # restored after the test
    bad = dataclasses.replace(config, routing={**config.routing, "teaching": ("gpt",)})
    engine = Engine(bad)
    with pytest.raises(ValueError, match="Unknown model provider 'gpt'"):
        engine.start()
    with pytest.raises(RuntimeError, match="closed"):
        engine.interactive.submit(lambda r: None)


def test_open_resources_builds_the_real_providers(config, monkeypatch, tmp_path):
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(tmp_path / "nlm"))
    r = open_resources(config)
    try:
        assert set(r.providers) == {"claude", "codex"}
        assert type(r.knowledge).__name__ == "GeminiNotebookProvider"
        assert r.courses.all() == [] and r.manifest.all() == []
    finally:
        r.close()
