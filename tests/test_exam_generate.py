"""BL-032: question generation, strict validation, one critique pass."""

import json
import logging
import re

import pytest

from core.context.compiler import ContextCompiler
from core.exams.coverage import plan
from core.exams.generate import QuestionGenerator, validate
from core.exams.spec import parse_spec
from core.ledger.ledger import Ledger
from core.memory.db import Manifest, ResourceRow, connect
from core.memory.learner import Concept, LearnerMemory
from core.router.router import Router
from tests.fakes.fake_exam import FakeQuestioner as Questioner
from tests.fakes.fake_exam import question
from tests.fakes.fake_knowledge import FakeKnowledge
from tests.fakes.fake_models import FakeModel

CONCEPTS = [
    Concept("cse220/pointers", "CSE220", "Pointers", week=3),
    Concept("cse220/bitwise-operators", "CSE220", "Bitwise operators", week=1),
]


def spec(**changes):
    doc = {
        "course": "CSE220",
        "exam": "Midterm 1",
        "formats": {"multiple_choice": 2, "short_answer": 2, "coding": 2},
        "difficulty": {"easy": 2, "medium": 2, "hard": 2},
        **changes,
    }
    return parse_spec(doc)


@pytest.fixture
def env(tmp_path):
    conn = connect(":memory:")
    learner = LearnerMemory(conn)
    for c in CONCEPTS:
        learner.upsert_concept(c)
    kp = FakeKnowledge(answer_text="Pointers hold addresses.")
    nb = kp.ensure_notebook("CSE220")
    manifest = Manifest(conn)
    for n, bucket in [(1, "lectures"), (2, "exams"), (3, "labs")]:
        path = tmp_path / f"{bucket}.pdf"
        path.write_text(bucket)
        manifest.upsert(
            ResourceRow(
                resource_id=f"r{n}",
                course="CSE220",
                title=bucket,
                added_at="",
                bucket=bucket,
                filename=f"{bucket}.pdf",
                notebook_id=nb,
                notebook_source_id=kp.add_file(nb, path),
            )
        )
    return conn, kp, manifest


def generator(env, claude, codex_reply="[]"):
    conn, kp, manifest = env
    models = {"claude": claude, "codex": FakeModel("codex", codex_reply)}
    ledger = Ledger(conn)
    gen = QuestionGenerator(
        Router(models, ledger, ["claude", "codex"]),
        Router(models, ledger, ["codex", "claude"]),
        ContextCompiler(kp, LearnerMemory(conn), manifest),
        manifest,
    )
    return gen, models


def test_a_plan_of_six_produces_six_valid_questions(env):
    p = plan(spec(), CONCEPTS, {})
    assert p.total == 6
    gen, models = generator(env, Questioner("claude"))

    report = gen.generate(p)

    assert len(report.questions) == 6
    for q in report.questions:
        validate({k: v for k, v in q.to_json().items() if k != "provider"})
    assert report.dropped == [] and report.regenerated == []
    assert sorted((q.format, q.difficulty) for q in report.questions) == sorted(
        (f, d) for r in p.rows for f, d in _pairs(r)
    )
    # one Questioner task per plan row, each grounded in NotebookLM
    assert len(models["claude"].tasks) == len(p.rows)
    assert all(
        t.task_type == "question_gen" and t.persona == "questioner" for t in models["claude"].tasks
    )
    assert "Pointers hold addresses." in models["claude"].tasks[0].user
    # the critic ran once, on the other provider
    (critique,) = models["codex"].tasks
    assert (critique.task_type, critique.persona) == ("critique", "critic")
    assert report.critic_provider == "codex" and report.generator_providers == ["claude"]


def _pairs(row):
    from core.exams.generate import slots

    return [(s.format, s.difficulty) for s in slots(row)]


def test_critic_flags_two_and_exactly_two_are_regenerated(env):
    flags = [
        {"index": 1, "issue": "two defensible answers", "fix": "say 'on a 64-bit machine'"},
        {"index": 4, "issue": "tagged hard but trivial", "fix": "ask for the general case"},
        {"index": 1, "issue": "duplicate flag", "fix": "ignored"},
        {"index": 99, "issue": "out of range", "fix": "ignored"},
    ]
    gen, models = generator(env, Questioner("claude"), json.dumps(flags))
    p = plan(spec(), CONCEPTS, {})

    report = gen.generate(p)
    rewrites = [t for t in models["claude"].tasks if "The Critic flagged" in t.user]

    assert report.regenerated == [1, 4]
    assert len(rewrites) == 2
    assert "two defensible answers" in rewrites[0].user
    assert len(report.questions) == 6
    assert len(models["codex"].tasks) == 1  # one critique pass only


def test_a_question_that_fails_validation_twice_is_dropped_and_logged(env, caplog):
    def spoil(task, items):
        # the pointers row's multiple-choice question has an answer key that isn't an option,
        # in the first draft and again on its retry
        for item in items:
            if item["concept_id"] == "cse220/pointers" and item["format"] == "multiple_choice":
                item["answer"] = "E"
                break
        return items

    gen, models = generator(env, Questioner("claude", spoil))
    p = plan(spec(), CONCEPTS, {})

    with caplog.at_level(logging.WARNING, logger="core.exams.generate"):
        report = gen.generate(p)

    assert len(report.questions) == 5
    (dropped,) = report.dropped
    assert "cse220/pointers multiple_choice" in dropped
    assert "answer is not one of the options" in dropped
    assert "Dropped a question after 2 tries" in caplog.text
    retries = [t for t in models["claude"].tasks if "was rejected" in t.user]
    assert len(retries) == 1


def test_an_invalid_question_regenerated_once_is_kept(env):
    calls = {"n": 0}

    def spoil(task, items):
        calls["n"] += 1
        if calls["n"] == 1:
            items[0]["level"] = 3  # an extra key: strict schema says no
        return items

    gen, _ = generator(env, Questioner("claude", spoil))
    report = gen.generate(plan(spec(), CONCEPTS, {}))
    assert len(report.questions) == 6 and report.dropped == []


def test_missing_questions_and_non_json_answers_are_retried_one_by_one(env):
    def spoil(task, items):
        if "Write exactly 1 question" in task.user:
            return items
        return items[:1] if "pointers" in task.user else "no JSON at all"

    gen, models = generator(env, Questioner("claude", spoil))
    p = plan(spec(), CONCEPTS, {})
    report = gen.generate(p)

    assert len(report.questions) == 6
    singles = [t for t in models["claude"].tasks if "Write exactly 1 question" in t.user]
    assert len(singles) == 5  # 2 missing from one row, all 3 from the other


def test_critic_never_runs_on_a_provider_that_wrote_questions(env):
    conn, kp, manifest = env
    claude = Questioner("claude")
    ledger = Ledger(conn)
    gen = QuestionGenerator(
        Router({"claude": claude}, ledger),
        Router({"claude": claude}, ledger),
        ContextCompiler(kp, LearnerMemory(conn), manifest),
    )
    report = gen.generate(plan(spec(), CONCEPTS, {}))
    assert report.critic_provider is None
    assert "no critic" in report.critique_skipped
    assert all(t.task_type == "question_gen" for t in claude.tasks)


def test_sources_limit_the_grounding_query_to_those_buckets(env):
    conn, kp, manifest = env
    gen, _ = generator(env, Questioner("claude"))
    gen.generate(plan(spec(sources=["lectures", "study-guides"]), CONCEPTS, {}))
    by_bucket = {r.notebook_source_id: r.bucket for r in manifest.all("CSE220")}
    for _, _, source_ids in kp.queries:
        assert sorted(by_bucket[s] for s in source_ids) == ["exams", "lectures"]


@pytest.mark.parametrize(
    "change, problem",
    [
        ({"options": None}, "multiple_choice needs 3-6 options"),
        ({"options": ["A", "A", "B", "C"]}, "options repeat"),
        ({"answer": "Z"}, "answer is not one of the options"),
        ({"difficulty": "brutal"}, "difficulty 'brutal'"),
        ({"stem": " "}, "stem must be a non-empty string"),
        ({"source": "lec3"}, "unexpected key(s) ['source']"),
    ],
)
def test_validate_is_strict(change, problem):
    item = {**question("cse220/pointers", "multiple_choice", "easy"), **change}
    item = {k: v for k, v in item.items() if v is not None}
    with pytest.raises(ValueError, match=re.escape(problem)):
        validate(item)


def test_validate_checks_the_slot_and_options_on_open_formats():
    from core.exams.generate import Slot

    with pytest.raises(ValueError, match="asked for"):
        validate(
            question("cse220/pointers", "coding", "easy"), Slot("cse220/pointers", "coding", "hard")
        )
    with pytest.raises(ValueError, match="have no options"):
        validate({**question("cse220/pointers", "coding", "easy"), "options": ["a", "b", "c"]})


def test_the_critics_verdicts_become_accuracy_and_groundedness(env):
    from core.router.benchmarks import Benchmarks

    flags = [
        {"index": 0, "kind": "grounding", "issue": "not in the sources", "fix": "cite lecture 3"},
        {"index": 2, "kind": "answer_key", "issue": "wrong key", "fix": "B is right"},
    ]
    gen, _ = generator(env, Questioner("claude"), json.dumps(flags))
    gen.generate(plan(spec(), CONCEPTS, {}))
    mark = Benchmarks(env[0]).for_task("question_gen")["claude"]
    assert mark.groundedness == pytest.approx(5 / 6)
    assert mark.accuracy == pytest.approx(5 / 6)
