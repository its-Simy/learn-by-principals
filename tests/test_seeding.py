import json
from contextlib import contextmanager

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
    draft_path,
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
    path, concepts = seed(kp, db, "CSE220", tmp_path / "memory")

    assert path == tmp_path / "memory/courses/CSE220/concepts.draft.yaml"
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
    assert first.unknown_prerequisites == [] and len(second.applied) == 2
    assert len(learner.concepts("CSE220")) == 2


def test_apply_reports_prerequisites_missing_from_the_draft(tmp_path, db):
    path = draft_path(tmp_path, "CSE220")
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

    mark_reviewed(tmp_path / "memory/courses/CSE220/concepts.draft.yaml")
    applied = runner.invoke(app, ["concepts", "apply", "--course", "CSE220"])
    assert applied.exit_code == 0, applied.output
    conn = connect(load_config().db_path)
    assert len(LearnerMemory(conn).concepts("CSE220")) == 2
