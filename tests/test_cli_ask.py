from contextlib import contextmanager

import pytest
from typer.testing import CliRunner

from cli.app import app
from core import wiring
from core.config import load_config
from core.memory.db import Manifest, ResourceRow, connect
from tests.fakes.fake_knowledge import FakeKnowledge

runner = CliRunner()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "home"))
    kp = FakeKnowledge(answer_text="Pointers are introduced with swap().")
    config = load_config()
    conn = connect(config.db_path)
    db = Manifest(conn)
    notebook_id = kp.ensure_notebook("CSE220")
    for n, bucket, name in [(1, "syllabus", "syllabus.pdf"), (2, "lectures", "lec3.pdf")]:
        path = tmp_path / name
        path.write_text(f"{name} text about pointers")
        source_id = kp.add_file(notebook_id, path)
        db.upsert(
            ResourceRow(
                resource_id=f"r{n}",
                course="CSE220",
                title=name,
                added_at="",
                filename=name,
                bucket=bucket,
                local_path=str(path),
                notebook_id=notebook_id,
                notebook_source_id=source_id,
                sync_state="synced",
            )
        )
    conn.close()

    @contextmanager
    def fake_open_knowledge(config, conn):
        yield kp

    monkeypatch.setattr(wiring, "open_knowledge", fake_open_knowledge)
    return kp


def test_ask_prints_answer_and_cited_source_titles(setup):
    result = runner.invoke(app, ["ask", "--course", "CSE220", "How are pointers introduced?"])
    assert result.exit_code == 0, result.output
    assert "Pointers are introduced with swap()." in result.output
    assert "[1] syllabus.pdf (syllabus)" in result.output
    assert setup.queries[-1][2] is None


def test_sources_filter_by_bucket(setup):
    result = runner.invoke(
        app, ["ask", "--course", "CSE220", "--sources", "lectures", "Lecture 3 pointers?"]
    )
    assert result.exit_code == 0, result.output
    (lecture_source,) = setup.queries[-1][2]
    assert setup.sources[lecture_source].path.name == "lec3.pdf"
    assert "lec3.pdf (lectures)" in result.output


def test_unknown_bucket_is_rejected(setup):
    result = runner.invoke(app, ["ask", "--course", "CSE220", "--sources", "memes", "q"])
    assert result.exit_code == 2


def test_bucket_with_no_sources_is_rejected(setup):
    result = runner.invoke(app, ["ask", "--course", "CSE220", "--sources", "exams", "q"])
    assert result.exit_code == 2
