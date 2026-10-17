from contextlib import contextmanager

import pytest
from typer.testing import CliRunner

from cli import common
from cli.app import app
from core.config import load_config
from core.memory.db import Courses, Manifest, ResourceRow, connect
from core.providers.storage.local import LocalStorageBackend
from core.sync.importer import Importer
from tests.fakes.fake_knowledge import FakeKnowledge

runner = CliRunner()


@pytest.fixture
def stored(tmp_path, monkeypatch):
    """Two courses with uploaded files, plus one link row (a URL, never sent to NotebookLM)."""
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BRIGHTLEARN_TMP_DIR", str(tmp_path / "tmp"))
    config = load_config()
    conn = connect(config.db_path)
    courses = Courses(conn)
    courses.add("CSE220", "Systems Fundamentals", "Fall-2026")
    courses.add("AMS161", "Applied Calculus II", "Fall-2026")
    importer = Importer(LocalStorageBackend(config.storage_root), Manifest(conn), courses)
    staged = tmp_path / "staged"
    staged.mkdir()
    for course, name, data in [
        ("CSE220", "lec1.pdf", b"one"),
        ("CSE220", "helloWorld.c", b"int main;"),
        ("CSE220", "policy.pdf", b"collaboration policy"),  # no keyword: the `other` bucket
        ("AMS161", "AMS161 Syllabus.pdf", b"s"),
    ]:
        (staged / name).write_bytes(data)
        importer.import_file(staged / name, course, name)
    Manifest(conn).upsert(
        ResourceRow(
            resource_id="topic:2",
            course="CSE220",
            title="Zoom",
            added_at="t",
            url="https://z",
            sync_state="link",
        )
    )
    conn.close()
    return config


@pytest.fixture(autouse=True)
def knowledge(monkeypatch) -> FakeKnowledge:
    kp = FakeKnowledge()

    @contextmanager
    def fake_open_knowledge(config, conn):
        yield kp

    monkeypatch.setattr(common, "open_knowledge", fake_open_knowledge)
    return kp


def added(knowledge) -> list[str]:
    return [c[1].name for c in knowledge.calls if c[0] == "add_file"]


def test_sync_links_one_courses_stored_files(stored, knowledge):
    result = runner.invoke(app, ["sync", "--course", "cse220"])

    assert result.exit_code == 0, result.output
    assert added(knowledge) == ["lec1.pdf", "policy.pdf"]  # code and links stay out
    assert "NotebookLM" in result.output
    rows = {r.filename: r for r in Manifest(connect(stored.db_path)).all("CSE220")}
    assert rows["policy.pdf"].bucket == "other"
    assert rows["lec1.pdf"].notebook_source_id in knowledge.sources
    assert rows["helloWorld.c"].notebook_source_id is None


def test_second_sync_makes_no_calls(stored, knowledge):
    assert runner.invoke(app, ["sync", "--course", "CSE220"]).exit_code == 0
    knowledge.calls.clear()

    result = runner.invoke(app, ["sync", "--course", "CSE220"])

    assert result.exit_code == 0
    assert knowledge.calls == []
    assert "CSE220 │ 0     │ 0        │ 0        │ 0" in result.output


def test_sync_all(stored, knowledge):
    result = runner.invoke(app, ["sync", "--all"])
    assert result.exit_code == 0, result.output
    assert sorted(added(knowledge)) == ["AMS161 Syllabus.pdf", "lec1.pdf", "policy.pdf"]


def test_include_code(stored, knowledge):
    result = runner.invoke(app, ["sync", "--course", "CSE220", "--include-code"])
    assert result.exit_code == 0, result.output
    assert sorted(added(knowledge)) == ["helloWorld.c", "lec1.pdf", "policy.pdf"]


@pytest.mark.parametrize("args", [[], ["--course", "CSE220", "--all"]])
def test_exactly_one_of_course_or_all(stored, args):
    assert runner.invoke(app, ["sync", *args]).exit_code == 2


def test_unknown_course(stored, knowledge):
    result = runner.invoke(app, ["sync", "--course", "CSE999"])
    assert result.exit_code == 2
    assert knowledge.calls == []


@pytest.mark.parametrize("gone", [["--dry-run"], ["--force"], ["--no-link"], ["--term", "X"]])
def test_download_options_are_gone(stored, gone):
    assert runner.invoke(app, ["sync", "--course", "CSE220", *gone]).exit_code == 2


def test_no_courses_yet(tmp_path, monkeypatch, knowledge):
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "home"))
    result = runner.invoke(app, ["sync", "--all"])
    assert result.exit_code == 0, result.output
    assert "courses add" in result.output
    assert knowledge.calls == []


def test_link_failures_exit_nonzero(stored, knowledge, monkeypatch):
    def boom(notebook_id, path):
        raise RuntimeError("upload refused")

    monkeypatch.setattr(knowledge, "add_file", boom)
    result = runner.invoke(app, ["sync", "--course", "CSE220"])
    assert result.exit_code == 1
    assert "upload refused" in result.output
