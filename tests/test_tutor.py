from contextlib import contextmanager

import pytest
from typer.testing import CliRunner

from cli import common
from cli.app import app
from core.config import load_config
from core.context.compiler import ContextCompiler
from core.ledger.ledger import Ledger
from core.memory.db import connect
from core.memory.learner import Concept, LearnerMemory
from core.memory.vault import Vault
from core.providers.models.base import ModelError, ProviderState
from core.router.router import Router
from core.tutor import Tutor
from tests.fakes.fake_knowledge import FakeKnowledge
from tests.fakes.fake_models import FakeModel

runner = CliRunner()


@pytest.fixture
def conn():
    return connect(":memory:")


@pytest.fixture
def models():
    return {"claude": FakeModel("claude", "Claude says hi."), "codex": FakeModel("codex", "Codex!")}


@pytest.fixture
def tutor(conn, models, tmp_path):
    learner = LearnerMemory(conn)
    learner.upsert_concept(Concept("cse220/pointers", "CSE220", "Pointers"))
    compiler = ContextCompiler(FakeKnowledge(answer_text="Pointers store addresses."), learner)
    router = Router(models, Ledger(conn), ["claude", "codex"])
    t = Tutor("CSE220", "simplifier", compiler, router, learner, Vault(tmp_path / "memory"))
    t.start()
    return t


def runs(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM model_runs ORDER BY rowid")]


def test_turn_compiles_routes_to_claude_and_appends_transcript(tutor, models, conn):
    reply = tutor.handle("What is a pointer?")

    assert reply == "Claude says hi."
    (task,) = models["claude"].tasks
    assert task.persona == "simplifier"
    assert "Pointers store addresses." in task.user
    text = tutor.transcript_path.read_text()
    assert "**Learner:** What is a pointer?" in text
    assert "**Tutor (simplifier · claude):** Claude says hi." in text
    (run,) = runs(conn)
    assert (run["provider"], run["task_type"], run["success"]) == ("claude", "explain", 1)


def test_rate_limited_claude_falls_back_to_codex(tutor, models, conn):
    models["claude"].limited = True

    assert tutor.handle("What is a pointer?") == "Codex!"
    assert tutor.handle("And a null pointer?") == "Codex!"

    first, second, third = runs(conn)
    assert (first["provider"], first["success"]) == ("claude", 0)
    assert (second["provider"], second["fallback_from"]) == ("codex", "claude")
    assert (third["provider"], third["fallback_from"]) == ("codex", "claude")  # claude skipped
    assert len(models["claude"].tasks) == 1
    assert models["claude"].state is ProviderState.RATE_LIMITED


def test_other_model_errors_do_not_fall_back(tutor, models, monkeypatch):
    def boom(task):
        raise ModelError("claude crashed")

    monkeypatch.setattr(models["claude"], "run", boom)
    assert tutor.handle("What is a pointer?") == "(no answer: claude crashed)"
    assert models["codex"].tasks == []


def test_persona_switch_mid_session(tutor, models):
    tutor.handle("What is a pointer?")
    assert tutor.handle("/persona exemplar") == "Persona: exemplar"
    tutor.handle("Show me one")
    assert [t.persona for t in models["claude"].tasks] == ["simplifier", "exemplar"]
    assert "Persona switched to exemplar" in tutor.transcript_path.read_text()


def test_analogist_without_anchor_is_refused(tutor):
    assert "staying with simplifier" in tutor.handle("/persona analogist")
    assert tutor.persona == "simplifier"


def test_session_context_carries_previous_turns(tutor, models):
    tutor.handle("What is a pointer?")
    tutor.handle("Why?")
    assert "Learner: What is a pointer?" in models["claude"].tasks[-1].user


def test_end_closes_the_session_and_runs_the_hook(conn, models, tmp_path):
    learner = LearnerMemory(conn)
    compiler = ContextCompiler(FakeKnowledge(), learner)
    ended = []
    t = Tutor(
        "CSE220",
        "simplifier",
        compiler,
        Router(models, Ledger(conn)),
        learner,
        Vault(tmp_path / "memory"),
        on_end=lambda tutor: ended.append(tutor.row.session_id) or "analyzed",
    )
    row = t.start()
    t.handle("What is a pointer?")

    assert t.handle("/end") == "Session ended. analyzed"
    assert ended == [row.session_id]
    saved = learner.get_session(row.session_id)
    assert saved.ended_at is not None
    assert saved.tutor_provider == "claude"


def test_cli_repl(tmp_path, monkeypatch, models):
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BRIGHTLEARN_VAULT", str(tmp_path / "memory"))
    kp = FakeKnowledge(answer_text="Pointers store addresses.")

    @contextmanager
    def fake_open_knowledge(config, conn):
        yield kp

    monkeypatch.setattr(common, "open_knowledge", fake_open_knowledge)
    monkeypatch.setattr(common, "open_model", lambda name, config: models[name])

    result = runner.invoke(
        app,
        ["tutor", "--course", "cse220"],
        input="What is a pointer?\n/persona exemplar\nShow one\n/end\n",
    )

    assert result.exit_code == 0, result.output
    assert "Claude says hi." in result.output
    (transcript,) = (tmp_path / "memory" / "sessions").glob("*.md")
    assert transcript.read_text().count("**Learner:**") == 2
    conn = connect(load_config().db_path)
    assert conn.execute("SELECT ended_at FROM sessions").fetchone()[0] is not None


def test_cli_rejects_unknown_persona(tmp_path, monkeypatch, models):
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "home"))

    @contextmanager
    def fake_open_knowledge(config, conn):
        yield FakeKnowledge()

    monkeypatch.setattr(common, "open_knowledge", fake_open_knowledge)
    monkeypatch.setattr(common, "open_model", lambda name, config: models[name])
    result = runner.invoke(app, ["tutor", "--course", "CSE220", "--persona", "comedian"])
    assert result.exit_code == 2
