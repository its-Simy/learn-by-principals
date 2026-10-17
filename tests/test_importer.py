"""BL-042: uploaded files land in the course's bucket tree with one manifest row each."""

import hashlib

import pytest
from typer.testing import CliRunner

from cli.app import app
from core.config import Config, load_config
from core.memory.db import Courses, Manifest, connect
from core.providers.storage.base import StorageError
from core.providers.storage.local import LocalStorageBackend
from core.sync.importer import Importer, UnknownBucket, UnknownCourse
from core.sync.link import LinkStep
from tests.fakes.fake_knowledge import FakeKnowledge

NOW = "2026-10-17T12:00:00+00:00"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def conn(config: Config):
    conn = connect(config.db_path)
    Courses(conn).add("CSE220", "Systems Fundamentals", "Fall-2026")
    yield conn
    conn.close()


@pytest.fixture
def db(conn) -> Manifest:
    return Manifest(conn)


@pytest.fixture
def storage(config: Config) -> LocalStorageBackend:
    return LocalStorageBackend(config.storage_root)


@pytest.fixture
def upload(storage, db, conn, tmp_path):
    """Stage ``data`` the way an upload does, then import it."""
    importer = Importer(storage, db, Courses(conn), now=lambda: NOW)
    staged = tmp_path / "staged"
    staged.mkdir()

    def run(name: str, data: bytes, course: str = "CSE220", bucket: str | None = None):
        src = staged / name
        src.write_bytes(data)
        return importer.import_file(src, course, name, bucket)

    return run


def course_root(config: Config):
    return config.storage_root.resolve() / "Fall-2026" / "CSE220"


def stored_files(config: Config) -> set[str]:
    root = course_root(config)
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def test_files_land_in_the_bucket_tree(upload, db, config, tmp_path):
    results = [
        upload("CSE220 Syllabus.pdf", b"syllabus"),
        upload("lec1.pdf", b"lecture one"),
        upload("helloWorld.c", b"int main;"),
    ]

    assert [r.outcome for r in results] == ["new", "new", "new"]
    assert stored_files(config) == {
        "syllabus/CSE220 Syllabus.pdf",
        "lectures/lec1.pdf",
        "code/helloWorld.c",
    }
    row = db.get(results[1].row.resource_id)
    assert row == results[1].row
    assert (row.course, row.bucket, row.filename, row.sync_state) == (
        "CSE220",
        "lectures",
        "lec1.pdf",
        "synced",
    )
    assert row.local_path == str(course_root(config) / "lectures" / "lec1.pdf")
    assert (row.hash, row.size, row.added_at) == (sha(b"lecture one"), len(b"lecture one"), NOW)
    assert len({r.row.resource_id for r in results}) == 3
    assert list((tmp_path / "staged").iterdir()) == []  # every staged file was consumed


def test_the_term_comes_from_the_course_row(upload, conn, config):
    Courses(conn).add("AMS161", "Applied Calculus II", "Spring-2027")
    result = upload("lec1.pdf", b"calc", course="AMS161")
    assert result.row.local_path == str(
        config.storage_root.resolve() / "Spring-2027" / "AMS161" / "lectures" / "lec1.pdf"
    )


def test_same_bytes_again_are_unchanged(upload, db, config):
    first = upload("lec1.pdf", b"lecture one")

    again = upload("lec1.pdf", b"lecture one")

    assert again.outcome == "unchanged"
    assert again.row == first.row
    assert len(db.all()) == 1
    assert stored_files(config) == {"lectures/lec1.pdf"}  # nothing kept in _versions/


def test_a_changed_linked_file_is_stale_and_its_old_version_kept(upload, db, config):
    first = upload("lec1.pdf", b"lecture one")
    kp = FakeKnowledge()
    LinkStep(kp, db).run("CSE220")
    linked = db.get(first.row.resource_id)

    changed = upload("lec1.pdf", b"lecture one, corrected")

    assert changed.outcome == "changed"
    row = changed.row
    assert row.resource_id == first.row.resource_id
    assert row.sync_state == "stale"
    assert row.notebook_source_id == linked.notebook_source_id  # replaced by the next link step
    assert row.hash == sha(b"lecture one, corrected")
    assert (course_root(config) / "lectures" / "lec1.pdf").read_bytes() == b"lecture one, corrected"
    (old,) = (course_root(config) / "lectures" / "_versions").iterdir()
    assert old.name == f"lec1.pdf.{sha(b'lecture one')[:8]}"
    assert old.read_bytes() == b"lecture one"

    # Uploaded again before the link step ran: NotebookLM still has the old bytes.
    assert upload("lec1.pdf", b"lecture one, corrected").row.sync_state == "stale"
    LinkStep(kp, db).run("CSE220")
    assert db.get(row.resource_id).sync_state == "synced"


def test_a_changed_file_not_yet_linked_stays_synced(upload):
    upload("lec1.pdf", b"v1")
    changed = upload("lec1.pdf", b"v2")
    assert (changed.outcome, changed.row.sync_state) == ("changed", "synced")


def test_an_explicit_bucket_wins_over_the_classifier(upload, config):
    result = upload("lec1.pdf", b"x", bucket="readings")
    assert result.row.bucket == "readings"
    assert stored_files(config) == {"readings/lec1.pdf"}


def test_the_same_name_in_another_bucket_is_another_file(upload, db):
    upload("notes.pdf", b"a")
    upload("notes.pdf", b"b", bucket="labs")
    assert sorted(r.bucket for r in db.all()) == ["labs", "lectures"]


def test_ambiguous_names_ask_the_fallback(storage, db, conn, tmp_path):
    asked = []

    def fallback(title, filename):
        asked.append((title, filename))
        return "labs"

    importer = Importer(storage, db, Courses(conn), classify_fallback=fallback)
    src = tmp_path / "dweight2.csv"
    src.write_text("1,2")
    assert importer.import_file(src, "CSE220", "dweight2.csv").row.bucket == "labs"
    assert asked == [("dweight2", "dweight2.csv")]


def test_an_unknown_course_is_refused_and_nothing_stored(upload, db, config, tmp_path):
    with pytest.raises(UnknownCourse):
        upload("lec1.pdf", b"x", course="CSE999")
    assert db.all() == []
    assert not (config.storage_root / "Fall-2026" / "CSE999").exists()
    assert (tmp_path / "staged" / "lec1.pdf").exists()  # still the caller's to delete


def test_an_unknown_bucket_is_refused(upload, db):
    with pytest.raises(UnknownBucket):
        upload("lec1.pdf", b"x", bucket="slides")
    assert db.all() == []


def test_a_store_failure_leaves_no_row(db, conn, config, tmp_path):
    class FullDisk(LocalStorageBackend):
        def store(self, src, rel_dir, name):
            raise StorageError("disk full")

    importer = Importer(FullDisk(config.storage_root), db, Courses(conn))
    src = tmp_path / "lec1.pdf"
    src.write_bytes(b"x")
    with pytest.raises(StorageError):
        importer.import_file(src, "CSE220", "lec1.pdf")
    assert db.all() == []


def test_courses_add_then_import(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BRIGHTLEARN_TERM", "Fall-2026")
    runner = CliRunner()
    added = runner.invoke(app, ["courses", "add", "cse220", "--name", "Systems Fundamentals"])
    assert added.exit_code == 0, added.output
    assert runner.invoke(app, ["courses", "add", "CSE220", "--name", "Again"]).exit_code == 2
    assert runner.invoke(app, ["courses", "add", "CSE 220", "--name", "Bad"]).exit_code == 2

    config = load_config()
    conn = connect(config.db_path)
    importer = Importer(LocalStorageBackend(config.storage_root), Manifest(conn), Courses(conn))
    src = tmp_path / "x.pdf"
    src.write_bytes(b"lecture")
    result = importer.import_file(src, "CSE220", "x.pdf", bucket="lectures")
    conn.close()
    assert result.row.local_path == str(
        config.storage_root.resolve() / "Fall-2026" / "CSE220" / "lectures" / "x.pdf"
    )

    listed = runner.invoke(app, ["courses", "list"])
    assert listed.exit_code == 0, listed.output
    assert "CSE220" in listed.output and "Systems Fundamentals" in listed.output
    assert "Fall-2026" in listed.output
