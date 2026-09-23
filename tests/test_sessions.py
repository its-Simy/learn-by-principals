"""P66: one live NotebookLM conversation per course."""

from contextlib import contextmanager

import pytest
from typer.testing import CliRunner

from cli import common
from cli.app import app
from core.config import load_config
from core.context.compiler import ContextCompiler
from core.ledger.ledger import Ledger
from core.memory.db import connect
from core.memory.learner import LearnerError, LearnerMemory
from core.memory.vault import Vault
from core.router.router import Router
from core.tutor import Tutor
from tests.fakes.fake_knowledge import FakeKnowledge
from tests.fakes.fake_models import FakeModel

runner = CliRunner()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BRIGHTLEARN_VAULT", str(tmp_path / "memory"))
    kp = FakeKnowledge(answer_text="Grounded.")

    @contextmanager
    def fake_open_knowledge(config, conn):
        yield kp

    monkeypatch.setattr(common, "open_knowledge", fake_open_knowledge)
    return kp


def open_session(course="CSE220"):
    conn = connect(load_config().db_path)
    row = LearnerMemory(conn).start_session(course)
    conn.close()
    return row


def test_ask_refuses_while_a_tutor_session_is_open(env):
    row = open_session()

    result = runner.invoke(app, ["ask", "--course", "cse220", "What is a pointer?"])

    assert result.exit_code == 1
    assert f"Tutor session {row.session_id} is open on CSE220" in result.output
    assert "/ask <question>" in result.output
    assert f"brightlearn sessions close --id {row.session_id}" in result.output
    assert env.queries == []  # NotebookLM never touched


def test_ask_on_another_course_is_not_blocked(env):
    open_session("CSE214")
    result = runner.invoke(app, ["ask", "--course", "CSE220", "q"])
    assert result.exit_code == 0, result.output
    assert "Grounded." in result.output


def test_ask_works_again_once_the_session_is_closed(env):
    row = open_session()
    closed = runner.invoke(app, ["sessions", "close", "--id", row.session_id])
    assert closed.exit_code == 0, closed.output
    assert f"Closed {row.session_id}" in closed.output

    result = runner.invoke(app, ["ask", "--course", "CSE220", "q"])
    assert result.exit_code == 0, result.output


def test_tutor_refuses_a_second_session_on_the_same_course(env, monkeypatch):
    open_session()
    monkeypatch.setattr(common, "open_model", lambda name, config: FakeModel(name))
    result = runner.invoke(app, ["tutor", "--course", "CSE220"], input="/end\n")
    assert result.exit_code == 1
    assert "is open on CSE220" in result.output
    conn = connect(load_config().db_path)
    assert len(LearnerMemory(conn).sessions()) == 1


def test_sessions_list_and_close_all(env):
    a, b = open_session("CSE220"), open_session("CSE214")

    listed = runner.invoke(app, ["sessions", "list", "--open"])
    assert listed.exit_code == 0, listed.output
    assert a.session_id in listed.output and b.session_id in listed.output

    closed = runner.invoke(app, ["sessions", "close", "--all"])
    assert closed.exit_code == 0, closed.output
    conn = connect(load_config().db_path)
    assert LearnerMemory(conn).open_sessions() == []
    assert runner.invoke(app, ["sessions", "list", "--open"]).output.strip() == "No sessions."


def test_sessions_close_needs_exactly_one_selector(env):
    assert runner.invoke(app, ["sessions", "close"]).exit_code == 2
    assert runner.invoke(app, ["sessions", "close", "--all", "--id", "x"]).exit_code == 2


def test_closing_an_unknown_or_ended_session_fails(env):
    assert runner.invoke(app, ["sessions", "close", "--id", "nope"]).exit_code == 1
    conn = connect(load_config().db_path)
    learner = LearnerMemory(conn)
    row = learner.start_session("CSE220")
    learner.close_session(row.session_id)
    with pytest.raises(LearnerError, match="already ended"):
        learner.close_session(row.session_id)


def test_every_tutor_query_uses_the_sessions_conversation(tmp_path):
    """Compiler queries and /ask inside a session never fall back to a fresh conversation."""
    conn = connect(":memory:")
    learner = LearnerMemory(conn)
    kp = FakeKnowledge(answer_text="Pointers store addresses.")
    router = Router({"claude": FakeModel("claude")}, Ledger(conn))
    tutor = Tutor(
        "CSE220", "simplifier", ContextCompiler(kp, learner), router, learner, Vault(tmp_path)
    )
    tutor.start()

    tutor.handle("What is a pointer?")
    answer = tutor.handle("/ask Where are pointers introduced?")
    tutor.handle("Why?")

    assert answer.startswith("Pointers store addresses.")
    assert len(kp.conversations) == 3
    assert set(kp.conversations) == {tutor.session.conversation.conversation_id}
    text = tutor.transcript_path.read_text()
    assert "**Ask (NotebookLM):** Where are pointers introduced?" in text
    assert tutor.handle("/ask") == "Usage: /ask <question>"
