"""BL-033: exam create -> take -> grade, end to end through the CLI with fakes."""

import json
from contextlib import contextmanager

import pytest
import yaml
from typer.testing import CliRunner

from cli import common
from cli.app import app
from core.analysis.challenge import ChallengeStore
from core.config import load_config
from core.exams.paper import LETTERS
from core.memory.db import connect
from core.memory.learner import Concept, LearnerMemory
from tests.fakes.fake_exam import FakeCritic, FakeQuestioner
from tests.fakes.fake_knowledge import FakeKnowledge

runner = CliRunner()
SPEC = {
    "course": "CSE220",
    "exam": "Midterm 1",
    "weeks": [1, 2],
    "formats": {"multiple_choice": 3, "short_answer": 2, "coding": 1},
    "difficulty": {"easy": 2, "medium": 2, "hard": 2},
    "mode": "realistic",
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BRIGHTLEARN_VAULT", str(tmp_path / "vault"))
    conn = connect(load_config().db_path)
    learner = LearnerMemory(conn)
    learner.upsert_concept(Concept("cse220/pointers", "CSE220", "Pointers", week=1))
    learner.upsert_concept(
        Concept("cse220/bitwise-operators", "CSE220", "Bitwise operators", week=2)
    )
    evidence = learner.add_evidence("cse220/pointers", "explained", "moderate")
    learner.set_mastery("cse220/pointers", 1, 0.6, [evidence])
    conn.close()
    models = {"claude": FakeQuestioner("claude"), "codex": FakeCritic("codex")}
    kp = FakeKnowledge(answer_text="Grounded source text.")

    @contextmanager
    def fake_open_knowledge(config, conn):
        yield kp

    monkeypatch.setattr(common, "open_knowledge", fake_open_knowledge)
    monkeypatch.setattr(common, "open_model", lambda name, config: models[name])
    spec = tmp_path / "cse220-midterm1.yaml"
    spec.write_text(yaml.safe_dump(SPEC))
    return spec, models, tmp_path


def create(spec):
    result = runner.invoke(app, ["exam", "create", "--spec", str(spec)])
    assert result.exit_code == 0, result.output
    (path,) = (spec.parent / "vault/courses/CSE220/exams").glob("*.json")
    return path, result


def script(exam, wrong=lambda q: q["difficulty"] == "hard", skip=()):
    """Answers for every question: right unless ``wrong(q)``; MC by letter, coding with /done."""
    lines = []
    for q in exam["questions"]:
        if q["index"] in skip:
            lines.append("/skip")
        elif q["format"] == "multiple_choice":
            right = q["options"].index(q["answer"])
            lines.append(LETTERS[(right + 1) % 4] if wrong(q) else LETTERS[right].lower())
        elif q["format"] == "coding":
            lines += [
                "int f(void) {",
                "  return 0;  // nope" if wrong(q) else "  return 1;  // correct",
                "}",
                "/done",
            ]
        else:
            lines.append("nope" if wrong(q) else "correct: it holds an address")
    return "\n".join(lines) + "\n"


def evidence_rows():
    conn = connect(load_config().db_path)
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM evidence WHERE session_id LIKE 'exam:%' ORDER BY rowid"
        )
    ]


def test_create_writes_json_and_markdown(env):
    spec, models, tmp = env
    path, result = create(spec)

    exam = json.loads(path.read_text())
    assert path.name.startswith("midterm-1-")
    assert len(exam["questions"]) == 6
    assert exam["generation"]["critic_provider"] == "codex"
    assert "6 of 6 questions" in result.output
    md = path.with_suffix(".md").read_text()
    assert md.startswith("# Midterm 1 · CSE220")
    assert md.index("## Answer key") > md.index("## 6.")
    assert [t.task_type for t in models["codex"].tasks] == ["critique"]


def test_create_take_grade_writes_one_evidence_row_per_answer(env):
    spec, models, _ = env
    path, _ = create(spec)
    exam = json.loads(path.read_text())

    taken = runner.invoke(app, ["exam", "take", str(path)], input=script(exam))
    assert taken.exit_code == 0, taken.output
    assert "All answered" in taken.output
    attempt = json.loads(path.read_text())["attempts"][0]
    assert attempt["finished_at"] and len(attempt["answers"]) == 6
    assert all(a["answered_at"] for a in attempt["answers"].values())

    graded = runner.invoke(app, ["exam", "grade", str(path)])

    assert graded.exit_code == 0, graded.output
    rows = evidence_rows()
    assert len(rows) == 6
    by_q = {int(r["excerpt_ref"].split(":")[0][1:]) - 1: r for r in rows}
    for q in exam["questions"]:
        row = by_q[q["index"]]
        if q["difficulty"] == "hard":  # answered wrong
            assert (row["type"], row["strength"]) == ("failed", "strong")
        else:
            assert row["type"] == "applied"
            assert row["strength"] == {"easy": "weak", "medium": "moderate"}[q["difficulty"]]
        assert row["source_provider"] == ("local" if q["format"] == "multiple_choice" else "codex")
    assert "Score 4/6 graded" in graded.output
    assert [t.task_type for t in models["codex"].tasks] == ["critique", "grade"]  # one grading call


def test_grading_twice_does_not_duplicate_evidence(env):
    spec, models, _ = env
    path, _ = create(spec)
    runner.invoke(app, ["exam", "take", str(path)], input=script(json.loads(path.read_text())))
    first = runner.invoke(app, ["exam", "grade", str(path)])
    before = evidence_rows()
    conn = connect(load_config().db_path)
    history = conn.execute("SELECT count(*) FROM mastery_history").fetchone()[0]

    second = runner.invoke(app, ["exam", "grade", str(path)])

    assert first.exit_code == second.exit_code == 0, second.output
    assert evidence_rows() == before
    assert conn.execute("SELECT count(*) FROM mastery_history").fetchone()[0] == history
    assert "0 new evidence row(s); 6 answer(s) were already graded" in second.output
    assert [t.task_type for t in models["codex"].tasks].count("grade") == 1


def test_mastery_moves_through_the_analyzer_rule_and_history(env):
    spec, _, _ = env
    path, _ = create(spec)
    exam = json.loads(path.read_text())
    runner.invoke(app, ["exam", "take", str(path)], input=script(exam, wrong=lambda q: False))
    graded = runner.invoke(app, ["exam", "grade", str(path)])
    assert graded.exit_code == 0, graded.output

    conn = connect(load_config().db_path)
    learner = LearnerMemory(conn)
    # Pointers: level 1, target 2, all correct -> +1 applied, citing this exam's evidence
    assert learner.get_mastery("cse220/pointers").level == 2
    change = learner.mastery_history("cse220/pointers")[-1]
    assert (change.old_level, change.new_level, change.changed_by) == (1, 2, "analyzer")
    exam_ids = {r["evidence_id"] for r in evidence_rows() if r["concept_id"] == "cse220/pointers"}
    assert set(change.evidence_ids) == exam_ids
    # Bitwise: level 0, target 2 -> a jump of 2 is not applied; it becomes a Challenger probe
    assert learner.get_mastery("cse220/bitwise-operators") is None
    (challenge,) = ChallengeStore(conn).all()
    assert (challenge.concept_id, challenge.reason) == (
        "cse220/bitwise-operators",
        "analyzer proposed 0 -> 2",
    )
    assert "1 → 2" in graded.output


def test_skipped_questions_write_no_evidence(env):
    spec, _, _ = env
    path, _ = create(spec)
    taken = runner.invoke(
        app, ["exam", "take", str(path)], input=script(json.loads(path.read_text()), skip={0})
    )
    assert taken.exit_code == 0, taken.output
    graded = runner.invoke(app, ["exam", "grade", str(path)])
    assert len(evidence_rows()) == 5
    assert "1 skipped" in graded.output


def test_take_resumes_after_quit_and_rejects_bad_choices(env):
    spec, _, _ = env
    path, _ = create(spec)
    exam = json.loads(path.read_text())
    first_mc = next(q for q in exam["questions"] if q["format"] == "multiple_choice")
    assert first_mc["index"] == 0  # MC questions come first for the first concept here

    quit_early = runner.invoke(app, ["exam", "take", str(path)], input="Z\nb\n/quit\n")
    assert quit_early.exit_code == 0, quit_early.output
    assert "pick one of the options by letter" in quit_early.output
    attempt = json.loads(path.read_text())["attempts"][0]
    assert list(attempt["answers"]) == ["0"] and attempt["finished_at"] is None

    refused = runner.invoke(app, ["exam", "grade", str(path)])
    assert refused.exit_code == 1 and "isn't finished" in refused.output

    lines = script(exam).splitlines()[1:]  # the rest, starting at question 2
    resumed = runner.invoke(app, ["exam", "take", str(path)], input="\n".join(lines) + "\n")
    assert resumed.exit_code == 0, resumed.output
    assert "Resuming attempt 1" in resumed.output
    exam = json.loads(path.read_text())
    assert len(exam["attempts"]) == 1 and len(exam["attempts"][0]["answers"]) == 6


def test_failed_open_grading_is_retried_without_regrading_the_rest(env):
    spec, models, _ = env
    path, _ = create(spec)
    runner.invoke(app, ["exam", "take", str(path)], input=script(json.loads(path.read_text())))
    models["codex"].limited = True
    partial = runner.invoke(app, ["exam", "grade", str(path)])
    assert partial.exit_code == 0, partial.output
    assert "3 answer(s) not graded yet" in partial.output
    assert len(evidence_rows()) == 3  # the multiple-choice answers

    # the rate limit's cooldown has passed and codex is healthy again
    models["codex"].limited = False
    models["codex"].state = models["codex"].state.AVAILABLE
    conn = connect(load_config().db_path)
    with conn:
        conn.execute("UPDATE provider_health SET cooldown_until = '2000-01-01T00:00:00+00:00'")
    retried = runner.invoke(app, ["exam", "grade", str(path)])
    assert retried.exit_code == 0, retried.output
    assert len(evidence_rows()) == 6


def test_create_refuses_while_a_tutor_session_is_open(env):
    spec, models, _ = env
    conn = connect(load_config().db_path)
    LearnerMemory(conn).start_session("CSE220")
    conn.close()
    result = runner.invoke(app, ["exam", "create", "--spec", str(spec)])
    assert result.exit_code == 1
    assert "is open on CSE220" in result.output
    assert models["claude"].tasks == []


def test_invalid_spec_is_a_usage_error(env, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({**SPEC, "length": 60}))
    result = runner.invoke(app, ["exam", "create", "--spec", str(bad)])
    assert result.exit_code == 2
