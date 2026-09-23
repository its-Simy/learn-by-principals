import pytest

from core.context.compiler import (
    LEARNER_CAP,
    SESSION_CAP,
    SOURCE_CAP,
    ContextCompiler,
    Turn,
    TutorSession,
    match_concepts,
)
from core.ledger.ledger import estimate_tokens
from core.memory.db import connect
from core.memory.learner import Concept, LearnerMemory
from core.personas import MissingAnchor
from core.providers.knowledge.base import KnowledgeRateLimited
from tests.fakes.fake_knowledge import FakeKnowledge

LONG = "Pointers hold the address of another object. " * 400  # far over any cap


@pytest.fixture
def learner():
    mem = LearnerMemory(connect(":memory:"))
    concepts = [
        ("cse220/pointers", "Pointers"),
        ("cse220/pointer-arithmetic", "Pointer arithmetic"),
        ("cse220/arrays", "Arrays"),
        ("cse220/structs", "Structs"),
    ]
    for cid, name in concepts:
        mem.upsert_concept(Concept(cid, "CSE220", name))
    e = mem.add_evidence(
        "cse220/pointer-arithmetic", "misconception", "moderate", excerpt_ref="p + 1 adds one byte"
    )
    mem.set_mastery("cse220/pointer-arithmetic", 1, 0.4, [e])
    e = mem.add_evidence("cse220/arrays", "applied", "strong")
    mem.set_mastery("cse220/arrays", 3, 0.8, [e])
    return mem


@pytest.fixture
def knowledge(tmp_path):
    kp = FakeKnowledge(answer_text=LONG)
    nb = kp.ensure_notebook("CSE220")
    lecture = tmp_path / "lec3.pdf"
    lecture.write_text("Lecture 3: pointers and pointer arithmetic. " * 20)
    kp.add_file(nb, lecture)
    return kp


def long_session(turns: int = 20) -> TutorSession:
    session = TutorSession("s1", "CSE220")
    for i in range(turns):
        role = "learner" if i % 2 == 0 else "tutor"
        session.turns.append(Turn(role, f"turn {i}: " + "blah " * 150))
    return session


def test_package_stays_under_budget_for_a_20_turn_session(knowledge, learner):
    compiler = ContextCompiler(knowledge, learner)
    package = compiler.compile(
        "How does pointer arithmetic work?", "CSE220", "simplifier", long_session()
    )

    report = package.metadata["context_report"]
    assert estimate_tokens(package.system) + estimate_tokens(package.user) < 3500
    assert report["total"] < 3500
    assert report["source"] <= SOURCE_CAP
    assert report["learner"] <= LEARNER_CAP
    assert report["session"] <= SESSION_CAP
    assert package.task_type == "explain"
    assert package.persona == "simplifier"
    assert "turn 19" in package.user and "turn 13" not in package.user  # last 6 turns at most


def test_matched_concepts_bring_their_learner_rows_and_misconceptions(knowledge, learner):
    package = ContextCompiler(knowledge, learner).compile(
        "How does pointer arithmetic work?", "CSE220", "simplifier"
    )
    assert package.metadata["concepts"] == ["cse220/pointer-arithmetic", "cse220/pointers"]
    assert "Pointer arithmetic: level 1/5" in package.user
    assert "misconception: p + 1 adds one byte" in package.user
    assert "Pointers: no evidence yet (level 0)" in package.user
    assert "[1] " in package.user  # citation line


def test_unmatched_question_has_empty_learner_context(knowledge, learner):
    package = ContextCompiler(knowledge, learner).compile(
        "What time is office hours?", "CSE220", "simplifier"
    )
    assert package.metadata["concepts"] == []
    assert package.metadata["context_report"]["learner"] == 0
    assert "## What this learner has shown\n(none)" in package.user
    assert package.system and package.user.endswith("What time is office hours?")


def test_analogist_gets_level_3_anchors(knowledge, learner):
    package = ContextCompiler(knowledge, learner).compile("Explain pointers", "CSE220", "analogist")
    assert "- Arrays (level 3)" in package.system
    assert package.task_type == "analogy"


def test_analogist_without_anchors_refuses(knowledge):
    empty = LearnerMemory(connect(":memory:"))
    with pytest.raises(MissingAnchor):
        ContextCompiler(knowledge, empty).compile("Explain pointers", "CSE220", "analogist")


def test_notebooklm_failure_still_produces_a_package(knowledge, learner, monkeypatch):
    def limited(*args, **kwargs):
        raise KnowledgeRateLimited("quota")

    monkeypatch.setattr(knowledge, "query", limited)
    package = ContextCompiler(knowledge, learner).compile("Explain pointers", "CSE220", "exemplar")
    assert "course sources unavailable" in package.user


def test_match_concepts_plural_and_all_words():
    concepts = [Concept("a", "C", "Pointer arithmetic"), Concept("b", "C", "Pointers")]
    assert [c.concept_id for c in match_concepts("pointers?", concepts)] == ["b"]
    assert [c.concept_id for c in match_concepts("the arithmetic of pointers", concepts)] == [
        "a",
        "b",
    ]
