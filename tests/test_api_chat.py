"""BL-045: the live tutor session, grounded asks and past sessions, with P66 across workers."""

import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
import yaml

from core.memory.db import Manifest, connect
from core.memory.learner import LearnerMemory
from core.providers.knowledge.base import KnowledgeError
from core.sessions import guard
from tests.test_api_courses_sources import add_course, parked, upload
from tests.test_exam_cli import SPEC


@pytest.fixture
def linked(api):
    """CSE220 with ``lec3.pdf`` uploaded and linked; ``(client, knowledge, models, engine)``."""
    client, kp, models, engine = api
    add_course(client)
    assert upload(client, "CSE220", "lec3.pdf").status_code == 200
    engine.drain()
    return api


def start(client, **body) -> dict:
    response = client.post("/api/courses/cse220/session", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def open_row(config, course: str = "CSE220", hours_ago: float = 0):
    """A session row opened elsewhere (the CLI, or a server that crashed)."""
    at = (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat(timespec="seconds")
    conn = connect(config.db_path)
    row = LearnerMemory(conn, now=lambda: at).start_session(course)
    conn.close()
    return row


# -- the live session ------------------------------------------------------------------------


def test_start_returns_the_live_session(linked):
    client, _, _, engine = linked
    response = client.post("/api/courses/cse220/session")  # no body: the default persona
    assert response.status_code == 200, response.text
    session = response.json()
    assert session == {
        "session_id": session["session_id"],
        "persona": "simplifier",
        "started_at": session["started_at"],
        "turns": [],
        "probe": None,
        "ended": False,
        "ratable": False,
    }
    assert client.get("/api/courses/CSE220/session").json() == session
    assert engine.live_sessions() == {"CSE220": session["session_id"]}
    (course,) = client.get("/api/courses").json()
    assert course["open_session_id"] == session["session_id"]


def test_start_with_another_persona_or_an_unknown_one(linked, config):
    client, _, _, engine = linked
    bad = client.post("/api/courses/CSE220/session", json={"persona": "nobody"})
    assert bad.status_code == 422
    assert engine.tutors == {}
    conn = connect(config.db_path)
    assert LearnerMemory(conn).sessions() == []  # refused before a row was written
    conn.close()
    assert start(client, persona="exemplar")["persona"] == "exemplar"


def test_a_turn_grows_the_session_and_its_transcript(linked):
    client, *_ = linked
    session = start(client)

    reply = client.post("/api/courses/CSE220/session/turn", json={"text": "What is a pointer?"})
    assert reply.status_code == 200, reply.text
    assert reply.json() == {
        "reply": "ok",  # FakeModel's answer
        "ended": False,
        "persona": "simplifier",
        "probe": None,
        "ratable": True,
    }
    live = client.get("/api/courses/CSE220/session").json()
    assert live["turns"] == [
        {"role": "learner", "text": "What is a pointer?"},
        {"role": "tutor", "text": "ok"},
    ]
    rated = client.post("/api/courses/CSE220/session/turn", json={"text": "/rate 4"}).json()
    assert rated["reply"] == "Rated the last answer 4/5."
    switched = client.post("/api/courses/CSE220/session/turn", json={"text": "/persona exemplar"})
    assert switched.json()["persona"] == "exemplar"

    text = client.get(f"/api/sessions/{session['session_id']}/transcript").json()["text"]
    assert "**Learner:** What is a pointer?" in text
    assert "_Rated 4/5 (claude)._" in text and "_Persona switched to exemplar._" in text


def test_a_turn_without_a_live_session_is_404(linked):
    client, *_ = linked
    response = client.post("/api/courses/CSE220/session/turn", json={"text": "hi"})
    assert response.status_code == 404
    assert client.post("/api/courses/CSE220/session/end").status_code == 404
    assert client.get("/api/courses/CSE220/session").json() is None
    assert client.post("/api/courses/CSE220/session/turn", json={"text": " "}).status_code == 422


def test_ask_in_a_session_uses_ground_in_the_sessions_conversation(linked):
    client, kp, _, engine = linked
    fresh = client.post("/api/courses/CSE220/ask", json={"question": "Before the session?"})
    before = fresh.json()
    assert before["in_session"] is False

    session = start(client)
    client.post("/api/courses/CSE220/session/turn", json={"text": "What is a pointer?"})
    asked = len(kp.conversations)
    response = client.post("/api/courses/CSE220/ask", json={"question": "Where is swap()?"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["in_session"] is True and body["citations"] == []
    # ``ground`` writes its citations into the text, labelled by filename.
    assert body["text"].startswith("Canned answer.") and "[1] lec3.pdf:" in body["text"]
    conversation = engine.tutors["CSE220"].session.conversation.conversation_id
    assert kp.conversations[asked:] == [conversation]
    assert kp.conversations[asked - 1] == conversation  # the turn's source context, too
    assert conversation not in kp.conversations[: asked - 1]  # the earlier ask was fresh
    text = client.get(f"/api/sessions/{session['session_id']}/transcript").json()["text"]
    assert "**Ask (NotebookLM):** Where is swap()?" in text

    filtered = client.post(
        "/api/courses/CSE220/ask", json={"question": "q", "source_ids": ["src2"]}
    )
    assert filtered.status_code == 422


def test_ask_without_a_session_cites_filename_and_bucket(linked):
    client, kp, _, _ = linked
    response = client.post("/api/courses/cse220/ask", json={"question": "Where is swap()?"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["in_session"] is False and body["text"] == "Canned answer."
    (citation,) = body["citations"]
    assert (citation["n"], citation["filename"], citation["bucket"]) == (1, "lec3.pdf", "lectures")
    assert citation["excerpt"] == "lec3.pdf text about pointers"
    assert kp.queries[-1][1:] == ("Where is swap()?", None)

    source_id = citation["source_id"]
    only = client.post("/api/courses/CSE220/ask", json={"question": "q", "source_ids": [source_id]})
    assert only.status_code == 200 and kp.queries[-1][2] == [source_id]
    for source_ids in (["src999"], []):
        bad = client.post(
            "/api/courses/CSE220/ask", json={"question": "q", "source_ids": source_ids}
        )
        assert bad.status_code == 422, source_ids
    assert client.post("/api/courses/CSE220/ask", json={"question": "  "}).status_code == 422


def test_ask_and_start_need_something_linked(api):
    client, kp, _, engine = api
    add_course(client)
    with parked(engine, "seed", "CSE214"):  # keep the link job from running
        assert upload(client, "CSE220", "lec3.pdf").status_code == 200
        ask = client.post("/api/courses/CSE220/ask", json={"question": "q"})
        assert ask.status_code == 422 and "Nothing from CSE220" in ask.json()["detail"]
        assert client.post("/api/courses/CSE220/session", json={}).status_code == 422
        assert kp.queries == [] and kp.notebooks == {}  # only the link job creates the notebook
        assert engine.tutors == {}


def test_a_course_whose_one_file_is_mid_replace_is_not_refused(linked, config):
    """Replacing a changed file, the link job clears its source id before adding it again. The
    course's notebook is still there then, so ``ensure_notebook`` only reads it back."""
    client, kp, _, engine = linked
    conn = connect(config.db_path)
    manifest = Manifest(conn)
    (row,) = manifest.all("CSE220")
    manifest.upsert(replace(row, notebook_source_id=None, source_hash=None))
    # FakeKnowledge keeps its notebooks to itself; without a ``notebooks`` row, nothing is linked.
    assert client.post("/api/courses/CSE220/ask", json={"question": "q"}).status_code == 422
    with conn:  # what the real provider records when it makes the notebook
        conn.execute(
            "INSERT INTO notebooks (course, notebook_id, created_at) VALUES (?, ?, ?)",
            ("CSE220", kp.ensure_notebook("CSE220"), "2026-10-17T10:00:00+00:00"),
        )
    conn.close()

    response = client.post("/api/courses/CSE220/ask", json={"question": "Where is swap()?"})

    assert response.status_code == 200, response.text
    (citation,) = response.json()["citations"]
    assert citation["filename"] is None  # its row is between remove and add
    start(client)
    assert "CSE220" in engine.tutors


# -- P66 across the workers ------------------------------------------------------------------


def test_a_second_start_is_409_session_open(linked):
    client, *_ = linked
    first = start(client)
    again = client.post("/api/courses/CSE220/session", json={})
    assert again.status_code == 409
    body = again.json()
    assert (body["code"], body["session_id"], body["stale"]) == (
        "session_open",
        first["session_id"],
        False,
    )


def test_start_and_ask_refuse_while_a_conversation_job_runs(linked, config):
    client, kp, _, engine = linked
    queried = len(kp.queries)
    with parked(engine, "seed") as job:
        response = client.post("/api/courses/CSE220/session", json={})
        assert response.status_code == 409
        body = response.json()
        assert (body["code"], body["job_id"], body["kind"]) == ("job_running", job.id, "seed")
        assert engine.tutors == {}

        # The jobs worker has its own provider: a fresh ask now would interleave with the job's.
        ask = client.post("/api/courses/CSE220/ask", json={"question": "q"})
        assert ask.status_code == 409 and ask.json()["code"] == "job_running"
        assert len(kp.queries) == queried
    conn = connect(config.db_path)
    assert LearnerMemory(conn).sessions() == []
    conn.close()

    with parked(engine, "link"):  # not a conversation job
        assert client.post("/api/courses/CSE220/ask", json={"question": "q"}).status_code == 200
        start(client)


SEED, EXAMS = "/api/courses/CSE220/concepts/seed", "/api/courses/CSE220/exams"
EXAM_SPEC = {"spec_yaml": yaml.dump(SPEC)}


def test_seed_and_exam_create_refuse_while_an_ask_is_answered(linked, monkeypatch):
    """P100: their jobs' fresh conversation would delete the one the ask is answered in."""
    client, kp, _, engine = linked
    asked, release = threading.Event(), threading.Event()
    real_query = kp.query

    def slow_query(*args, **kwargs):
        asked.set()
        assert release.wait(10)
        return real_query(*args, **kwargs)

    monkeypatch.setattr(kp, "query", slow_query)
    answers = []
    asker = threading.Thread(
        target=lambda: answers.append(
            client.post("/api/courses/CSE220/ask", json={"question": "Where is swap()?"})
        )
    )
    asker.start()
    try:
        assert asked.wait(10)
        for url, body in ((SEED, None), (EXAMS, EXAM_SPEC)):
            refused = client.post(url, json=body)
            assert refused.status_code == 409, url
            assert set(refused.json()) == {"code", "detail"}
            assert refused.json()["code"] == "ask_running"
        assert engine.asking == {"CSE220"}
        assert [j.kind for j in engine.jobs.all("CSE220")] == ["link"]  # nothing queued
    finally:
        release.set()
        asker.join(10)

    (answer,) = answers
    assert answer.status_code == 200, answer.text
    assert engine.asking == set()
    for url, body, kind in ((SEED, None, "seed"), (EXAMS, EXAM_SPEC, "exam_create")):
        queued = client.post(url, json=body)
        assert queued.status_code == 200, queued.text
        assert queued.json()["kind"] == kind
    engine.drain()


def test_an_ask_that_fails_lets_seed_through(linked, monkeypatch):
    client, kp, _, engine = linked

    def broken_query(*args, **kwargs):
        raise KnowledgeError("notebook gone")

    monkeypatch.setattr(kp, "query", broken_query)
    assert client.post("/api/courses/CSE220/ask", json={"question": "q"}).status_code == 502
    bad = client.post("/api/courses/CSE220/ask", json={"question": "q", "source_ids": ["nope"]})
    assert bad.status_code == 422
    assert engine.asking == set()
    assert client.post(SEED).status_code == 200
    engine.drain()


def test_a_conversation_job_fails_while_a_session_is_open(linked):
    """Exam create and seed jobs ``guard`` first, so a session started in the API stops them."""
    client, _, _, engine = linked
    session = start(client)
    job = engine.jobs.submit("exam_create", "CSE220", lambda r: guard(r.learner, "CSE220"))
    engine.drain()
    failed = client.get(f"/api/jobs/{job.id}").json()
    assert failed["status"] == "failed"
    assert f"Tutor session {session['session_id']} is open on CSE220" in failed["error"]


def test_a_session_open_elsewhere_blocks_ask_and_start(linked, config):
    client, *_ = linked
    row = open_row(config)
    for response in (
        client.post("/api/courses/CSE220/ask", json={"question": "q"}),
        client.post("/api/courses/CSE220/session", json={}),
    ):
        assert response.status_code == 409
        assert response.json()["code"] == "session_open"
        assert response.json()["session_id"] == row.session_id


# -- past sessions ---------------------------------------------------------------------------


def test_a_stale_session_is_listed_stale_and_can_be_closed(linked, config):
    client, *_ = linked
    row = open_row(config, hours_ago=3)

    (listed,) = client.get("/api/courses/CSE220/sessions").json()
    assert (listed["session_id"], listed["state"], listed["live"]) == (
        row.session_id,
        "stale",
        False,
    )
    blocked = client.post("/api/courses/CSE220/session", json={})
    assert blocked.status_code == 409 and blocked.json()["stale"] is True

    closed = client.post(f"/api/sessions/{row.session_id}/close")
    assert closed.status_code == 200, closed.text
    assert closed.json()["state"] == "ended" and closed.json()["ended_at"]
    assert client.post(f"/api/sessions/{row.session_id}/close").status_code == 422  # already
    assert client.post("/api/sessions/nope/close").status_code == 404
    start(client)


def test_closing_the_live_session_is_409(linked):
    client, _, _, engine = linked
    session = start(client)
    response = client.post(f"/api/sessions/{session['session_id']}/close")
    assert response.status_code == 409
    assert set(response.json()) == {"code", "detail", "session_id"}
    assert response.json()["code"] == "session_live"
    assert response.json()["session_id"] == session["session_id"]
    (listed,) = client.get("/api/courses/CSE220/sessions").json()
    assert (listed["state"], listed["live"], listed["ended_at"]) == ("open", True, None)
    assert "CSE220" in engine.tutors


def test_transcript(linked, config):
    client, *_ = linked
    session = start(client)
    response = client.get(f"/api/sessions/{session['session_id']}/transcript")
    assert response.status_code == 200
    assert f"# Tutor session {session['session_id']} · CSE220" in response.json()["text"]

    assert client.get("/api/sessions/nope/transcript").status_code == 404
    elsewhere = open_row(config, "CSE214")  # a row whose transcript was never written
    assert client.get(f"/api/sessions/{elsewhere.session_id}/transcript").status_code == 404


def test_end_sets_ended_at_and_empties_the_registry(linked):
    client, _, _, engine = linked
    session = start(client)
    client.post("/api/courses/CSE220/session/turn", json={"text": "What is a pointer?"})

    response = client.post("/api/courses/CSE220/session/end")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ended"] is True and body["reply"].startswith("Session ended.")
    assert engine.tutors == {} and engine.live_sessions() == {}
    assert client.get("/api/courses/CSE220/session").json() is None
    (listed,) = client.get("/api/courses/CSE220/sessions").json()
    assert listed["session_id"] == session["session_id"]
    assert (listed["state"], listed["live"]) == ("ended", False) and listed["ended_at"]
    assert client.post("/api/courses/CSE220/session/end").status_code == 404

    # ``/end`` as a turn does the same.
    start(client)
    ended = client.post("/api/courses/CSE220/session/turn", json={"text": "/end"}).json()
    assert ended["ended"] is True and engine.tutors == {}
