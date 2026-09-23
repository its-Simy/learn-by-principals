import json
from contextlib import contextmanager
from datetime import datetime

import pytest
import yaml
from typer.testing import CliRunner

from cli import common
from cli.app import app
from core.config import load_config
from core.memory.db import Manifest, ResourceRow, connect
from core.memory.learner import LearnerMemory
from core.memory.seeding import (
    DraftNotReviewed,
    SeedingError,
    apply,
    draft_diff,
    drafts_dir,
    latest_draft,
    list_drafts,
    new_draft_path,
    parse_concepts,
    seed,
)
from tests.fakes.fake_knowledge import FakeKnowledge

CANNED = [
    {
        "name": "Pointers",
        "module": "Memory",
        "week": 3,
        "prerequisites": ["Data representation"],
        "exam_tags": ["midterm-1"],
    },
    {
        "name": "Data representation",
        "module": "Bits",
        "week": 1,
        "prerequisites": [],
        "exam_tags": ["midterm-1"],
    },
]

runner = CliRunner()


def canned_answer() -> str:
    return "Here you go:\n```json\n" + json.dumps(CANNED) + "\n```\n[1]"


@pytest.fixture
def kp():
    return FakeKnowledge(answer_text=canned_answer())


@pytest.fixture
def db():
    conn = connect(":memory:")
    db = Manifest(conn)
    for topic_id, bucket, title in [(1, "syllabus", "Syllabus"), (2, "lectures", "Lecture 3")]:
        db.upsert(
            ResourceRow(
                course="CSE220",
                org_unit_id=1,
                topic_id=topic_id,
                module_path="",
                title=title,
                type_identifier="File",
                last_seen="",
                bucket=bucket,
                notebook_source_id=f"src{topic_id}",
            )
        )
    return db


def mark_reviewed(path):
    path.write_text(path.read_text().replace("reviewed: false", "reviewed: true"))


def test_seed_writes_an_unreviewed_draft(kp, db, tmp_path):
    path, concepts = seed(kp, db, "CSE220", tmp_path / "memory", now=datetime(2026, 9, 23, 14, 30))

    assert path == tmp_path / "memory/courses/CSE220/concepts.draft.20260923-143000.yaml"
    doc = yaml.safe_load(path.read_text())
    assert doc["reviewed"] is False
    assert [c["name"] for c in doc["concepts"]] == ["Pointers", "Data representation"]
    assert doc["concepts"][0]["week"] == 3
    notebook_id, prompt, source_ids = kp.queries[-1]
    assert "- Lecture 3" in prompt
    assert source_ids == ["src1", "src2"]


def test_apply_refuses_an_unreviewed_draft(kp, db, tmp_path):
    path, _ = seed(kp, db, "CSE220", tmp_path)
    learner = LearnerMemory(db.conn)
    with pytest.raises(DraftNotReviewed):
        apply(path, learner)
    assert learner.concepts("CSE220") == []


def test_apply_inserts_rows_and_is_idempotent(kp, db, tmp_path):
    path, _ = seed(kp, db, "CSE220", tmp_path)
    mark_reviewed(path)
    learner = LearnerMemory(db.conn)

    first = apply(path, learner)
    second = apply(path, learner)

    concepts = learner.concepts("CSE220")
    assert [c.concept_id for c in concepts] == ["cse220/data-representation", "cse220/pointers"]
    assert learner.get_concept("cse220/pointers").prerequisites == ["cse220/data-representation"]
    assert learner.get_concept("cse220/pointers").exam_tags == ["midterm-1"]
    assert learner.get_concept("cse220/pointers").week == 3  # kept for the ExamSpec (BL-031)
    assert first.unknown_prerequisites == [] and len(second.applied) == 2
    assert len(learner.concepts("CSE220")) == 2


def test_apply_reports_prerequisites_missing_from_the_draft(tmp_path, db):
    path = new_draft_path(tmp_path, "CSE220")
    path.parent.mkdir(parents=True)
    path.write_text(
        yaml.safe_dump(
            {
                "course": "CSE220",
                "reviewed": True,
                "concepts": [{"name": "Pointers", "prerequisites": ["Addresses"]}],
            }
        )
    )
    result = apply(path, LearnerMemory(db.conn))
    assert result.unknown_prerequisites == ["Addresses"]


def test_parse_concepts_rejects_non_json():
    with pytest.raises(SeedingError):
        parse_concepts("I couldn't find a syllabus.")


def test_cli_seed_then_apply(kp, tmp_path, monkeypatch):
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BRIGHTLEARN_VAULT", str(tmp_path / "memory"))

    @contextmanager
    def fake_open_knowledge(config, conn):
        yield kp

    monkeypatch.setattr(common, "open_knowledge", fake_open_knowledge)

    seeded = runner.invoke(app, ["concepts", "seed", "--course", "cse220"])
    assert seeded.exit_code == 0, seeded.output
    assert "2 concepts drafted" in seeded.output

    refused = runner.invoke(app, ["concepts", "apply", "--course", "CSE220"])
    assert refused.exit_code == 1

    mark_reviewed(latest_draft(tmp_path / "memory", "CSE220"))
    applied = runner.invoke(app, ["concepts", "apply", "--course", "CSE220"])
    assert applied.exit_code == 0, applied.output
    conn = connect(load_config().db_path)
    assert len(LearnerMemory(conn).concepts("CSE220")) == 2


# -- P65: seed never overwrites a draft ------------------------------------------------------


def test_reseeding_keeps_the_reviewed_draft_and_writes_a_new_one(kp, db, tmp_path):
    vault = tmp_path / "memory"
    first, _ = seed(kp, db, "CSE220", vault, now=datetime(2026, 9, 23, 14, 30))
    mark_reviewed(first)
    reviewed = first.read_text()

    kp.answer_text = canned_answer().replace("Pointers", "Pointer basics")
    second, _ = seed(kp, db, "CSE220", vault, now=datetime(2026, 9, 24, 9, 0))

    assert first.read_text() == reviewed
    assert second.name == "concepts.draft.20260924-090000.yaml"
    assert list_drafts(vault, "CSE220") == [first, second]
    diff = draft_diff(first, second)
    assert diff.startswith("--- concepts.draft.20260923-143000.yaml\n+++ ")
    assert "-reviewed: true\n+reviewed: false" in diff
    assert "+- name: Pointer basics" in diff


def test_same_second_seed_gets_a_suffix_not_an_overwrite(kp, db, tmp_path):
    now = datetime(2026, 9, 23, 14, 30)
    first, _ = seed(kp, db, "CSE220", tmp_path, now=now)
    second, _ = seed(kp, db, "CSE220", tmp_path, now=now)
    third, _ = seed(kp, db, "CSE220", tmp_path, now=now)

    assert [p.name for p in (first, second, third)] == [
        "concepts.draft.20260923-143000.yaml",
        "concepts.draft.20260923-143000-2.yaml",
        "concepts.draft.20260923-143000-3.yaml",
    ]
    assert list_drafts(tmp_path, "CSE220") == [first, second, third]


def test_legacy_draft_counts_as_the_oldest(kp, db, tmp_path):
    legacy = drafts_dir(tmp_path, "CSE220") / "concepts.draft.yaml"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("course: CSE220\nreviewed: true\nconcepts: []\n")
    new, _ = seed(kp, db, "CSE220", tmp_path)
    assert list_drafts(tmp_path, "CSE220") == [legacy, new]
    assert legacy.read_text().startswith("course: CSE220")


def test_cli_seed_prints_a_diff_against_the_newest_draft(kp, tmp_path, monkeypatch):
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BRIGHTLEARN_VAULT", str(tmp_path / "memory"))

    @contextmanager
    def fake_open_knowledge(config, conn):
        yield kp

    monkeypatch.setattr(common, "open_knowledge", fake_open_knowledge)
    assert runner.invoke(app, ["concepts", "seed", "--course", "CSE220"]).exit_code == 0
    first = latest_draft(tmp_path / "memory", "CSE220")
    mark_reviewed(first)

    kp.answer_text = canned_answer().replace("Pointers", "Pointer basics")
    again = runner.invoke(app, ["concepts", "seed", "--course", "CSE220"])

    assert again.exit_code == 0, again.output
    assert f"--- {first.name}" in again.output
    assert "+- name: Pointer basics" in again.output
    assert "reviewed: true" in first.read_text()
    assert len(list_drafts(tmp_path / "memory", "CSE220")) == 2

    # apply takes the newest draft, which isn't reviewed yet; --draft picks the reviewed one
    refused = runner.invoke(app, ["concepts", "apply", "--course", "CSE220"])
    assert refused.exit_code == 1
    assert "pick one with --draft" in refused.output
    chosen = runner.invoke(app, ["concepts", "apply", "--course", "CSE220", "--draft", first.name])
    assert chosen.exit_code == 0, chosen.output
    conn = connect(load_config().db_path)
    assert [c.name for c in LearnerMemory(conn).concepts("CSE220")] == [
        "Data representation",
        "Pointers",
    ]


def test_cli_seed_refuses_while_a_tutor_session_is_open(kp, tmp_path, monkeypatch):
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BRIGHTLEARN_VAULT", str(tmp_path / "memory"))
    conn = connect(load_config().db_path)
    LearnerMemory(conn).start_session("CSE220")
    conn.close()

    @contextmanager
    def fake_open_knowledge(config, conn):
        yield kp

    monkeypatch.setattr(common, "open_knowledge", fake_open_knowledge)
    result = runner.invoke(app, ["concepts", "seed", "--course", "CSE220"])
    assert result.exit_code == 1
    assert "is open on CSE220" in result.output
    assert kp.queries == []
