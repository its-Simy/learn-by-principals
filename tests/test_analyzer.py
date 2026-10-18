import json
from contextlib import contextmanager

import pytest
from typer.testing import CliRunner

from cli.app import app
from core import wiring
from core.analysis.analyzer import AnalysisError, Analyzer
from core.config import load_config
from core.ledger.ledger import Ledger
from core.memory.db import connect
from core.memory.learner import Concept, LearnerMemory
from core.memory.vault import Vault, read_front_matter
from core.router.router import Router
from tests.fakes.fake_knowledge import FakeKnowledge
from tests.fakes.fake_models import FakeModel

OUTPUT = [
    {
        "concept": "Pointers",
        "evidence_type": "applied",
        "strength": "strong",
        "excerpt": "Learner: so *p reads the int that p points to",
        "proposed_level": 3,
    },
    {
        "concept": "Pointer arithmetic",
        "evidence_type": "transferred",
        "strength": "moderate",
        "excerpt": "Learner: p + 1 moves by sizeof(int)",
        "proposed_level": 3,
    },
    {
        "concept": "Linked lists",
        "evidence_type": "explained",
        "strength": "weak",
        "excerpt": "x",
        "proposed_level": 1,
    },
]


@pytest.fixture
def learner():
    mem = LearnerMemory(connect(":memory:"))
    mem.upsert_concept(Concept("cse220/pointers", "CSE220", "Pointers"))
    mem.upsert_concept(Concept("cse220/pointer-arithmetic", "CSE220", "Pointer arithmetic"))
    e = mem.add_evidence("cse220/pointers", "explained", "moderate")
    mem.set_mastery("cse220/pointers", 2, 0.6, [e])
    return mem


@pytest.fixture
def models():
    reply = "```json\n" + json.dumps(OUTPUT) + "\n```"
    return {"claude": FakeModel("claude", reply), "codex": FakeModel("codex", reply)}


TRANSCRIPT = """# Tutor session s · CSE220

**Learner:** What does *p do?

**Tutor (simplifier · claude):** It follows the pointer. What does it give you here?

**Learner:** so *p reads the int that p points to

**Tutor (simplifier · claude):** Right. And p + 1?

**Learner:** p + 1 moves by sizeof(int), not one byte
"""


def session(learner, tutor_provider="claude"):
    row = learner.start_session("CSE220", tutor_provider=tutor_provider)
    row.tutor_provider = tutor_provider
    return row


def analyzer(learner, models, tmp_path):
    router = Router(models, Ledger(learner.conn), ["claude", "codex"])
    return Analyzer(router, learner, Vault(tmp_path / "memory"))


def test_evidence_written_plus_one_applied_plus_three_logged(learner, models, tmp_path):
    row = session(learner)

    report = analyzer(learner, models, tmp_path).analyze(row, TRANSCRIPT)

    assert report.provider == "codex"  # never the tutor
    assert models["claude"].tasks == []
    assert len(report.evidence_ids) == 2
    evidence = learner.evidence("cse220/pointers")
    assert evidence[-1].type == "applied"
    assert evidence[-1].session_id == row.session_id
    assert evidence[-1].source_provider == "codex"
    assert evidence[-1].excerpt_ref.startswith("Learner: so *p")

    # +1 (2 -> 3) applied, justified by this session's evidence
    assert [(c.concept_id, c.current, c.proposed) for c in report.applied] == [
        ("cse220/pointers", 2, 3)
    ]
    assert learner.get_mastery("cse220/pointers").level == 3
    # +3 (0 -> 3) logged, not applied
    assert [(c.concept_id, c.current, c.proposed) for c in report.needs_challenge] == [
        ("cse220/pointer-arithmetic", 0, 3)
    ]
    assert learner.get_mastery("cse220/pointer-arithmetic") is None
    assert report.skipped == ["unknown concept 'Linked lists'"]


def test_session_row_and_summary_record_the_analysis(learner, models, tmp_path):
    row = session(learner)
    analyzer(learner, models, tmp_path).analyze(row, TRANSCRIPT)

    saved = learner.get_session(row.session_id)
    assert saved.analyzer_provider == "codex"
    front = read_front_matter(tmp_path / "memory" / "sessions" / f"{row.session_id}.summary.md")
    assert front["analyzer_provider"] == "codex"
    text = (tmp_path / "memory" / "sessions" / f"{row.session_id}.summary.md").read_text(
        encoding="utf-8"
    )
    assert "needs_challenge: cse220/pointer-arithmetic 0 -> 3" in text


def test_codex_tutored_session_is_analyzed_by_claude(learner, models, tmp_path):
    report = analyzer(learner, models, tmp_path).analyze(session(learner, "codex"), TRANSCRIPT)
    assert report.provider == "claude"
    assert models["codex"].tasks == []


def test_both_providers_tutored_leaves_no_analyzer(learner, models, tmp_path):
    with pytest.raises(AnalysisError, match="No model provider left"):
        analyzer(learner, models, tmp_path).analyze(session(learner, "claude,codex"), "t")


def test_non_json_output_is_an_error(learner, tmp_path):
    models = {"claude": FakeModel("claude"), "codex": FakeModel("codex", "Great session!")}
    with pytest.raises(AnalysisError, match="JSON"):
        analyzer(learner, models, tmp_path).analyze(session(learner), "t")


def test_empty_array_writes_nothing(learner, tmp_path):
    models = {"claude": FakeModel("claude"), "codex": FakeModel("codex", "[]")}
    report = analyzer(learner, models, tmp_path).analyze(session(learner), "t")
    assert report.evidence_ids == [] and report.applied == []


def test_tutor_end_runs_the_analyzer(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BRIGHTLEARN_VAULT", str(tmp_path / "memory"))
    conn = connect(load_config().db_path)
    LearnerMemory(conn).upsert_concept(Concept("cse220/pointers", "CSE220", "Pointers"))
    conn.close()
    reply = json.dumps([{**OUTPUT[0], "excerpt": "What is a pointer?", "proposed_level": 1}])
    models = {"claude": FakeModel("claude", "Tutor reply."), "codex": FakeModel("codex", reply)}

    @contextmanager
    def fake_open_knowledge(config, conn):
        yield FakeKnowledge()

    monkeypatch.setattr(wiring, "open_knowledge", fake_open_knowledge)
    monkeypatch.setattr(wiring, "open_model", lambda name, config: models[name])

    result = CliRunner().invoke(
        app, ["tutor", "--course", "CSE220"], input="What is a pointer?\n/end\n"
    )

    assert result.exit_code == 0, result.output
    assert "Analyzer (codex): 1 evidence, 1 mastery change" in result.output
    conn = connect(load_config().db_path)
    assert LearnerMemory(conn).get_mastery("cse220/pointers").level == 1
    assert models["codex"].tasks[0].task_type == "analyze_transcript"
    assert "What is a pointer?" in models["codex"].tasks[0].user


def test_excerpts_the_learner_never_said_are_not_written(learner, tmp_path):
    items = [
        {**OUTPUT[0], "excerpt": "It follows the pointer."},  # the tutor's words
        {**OUTPUT[0], "excerpt": "pointers are just integers"},  # invented
        {**OUTPUT[0], "excerpt": ""},
        {**OUTPUT[0], "excerpt": '"So *p reads the int…"', "proposed_level": 3},
    ]
    models = {"claude": FakeModel("claude"), "codex": FakeModel("codex", json.dumps(items))}
    before = len(learner.evidence("cse220/pointers"))

    report = analyzer(learner, models, tmp_path).analyze(session(learner), TRANSCRIPT)

    assert len(report.evidence_ids) == 1  # only the quoted learner line
    assert len(learner.evidence("cse220/pointers")) == before + 1
    assert report.skipped.count("Pointers: excerpt is not in the learner's own turns") == 3
    (change,) = learner.mastery_history("cse220/pointers")[-1:]
    assert change.changed_by == "analyzer"
    assert change.evidence_ids == report.evidence_ids


def test_routing_order_comes_from_config_toml(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text(
        '[routing]\nteaching = ["codex", "claude"]\nanalysis = ["claude", "codex"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(home))
    monkeypatch.setenv("BRIGHTLEARN_VAULT", str(tmp_path / "memory"))
    models = {"claude": FakeModel("claude", "[]"), "codex": FakeModel("codex", "Codex teaches.")}

    @contextmanager
    def fake_open_knowledge(config, conn):
        yield FakeKnowledge()

    monkeypatch.setattr(wiring, "open_knowledge", fake_open_knowledge)
    monkeypatch.setattr(wiring, "open_model", lambda name, config: models[name])

    result = CliRunner().invoke(app, ["tutor", "--course", "CSE220"], input="Hi?\n/end\n")

    assert result.exit_code == 0, result.output
    assert "Codex teaches." in result.output
    assert "Analyzer (claude)" in result.output


def test_the_excerpt_check_is_recorded_as_groundedness(learner, tmp_path):
    from core.router.benchmarks import Benchmarks

    items = [
        {**OUTPUT[0], "excerpt": "It follows the pointer."},  # the tutor's words
        {**OUTPUT[0], "excerpt": "so *p reads the int that p points to"},
    ]
    models = {"claude": FakeModel("claude"), "codex": FakeModel("codex", json.dumps(items))}
    analyzer(learner, models, tmp_path).analyze(session(learner), TRANSCRIPT)
    mark = Benchmarks(learner.conn).for_task("analyze_transcript")["codex"]
    assert mark.groundedness == 0.5
    assert mark.format_compliance == 1.0
