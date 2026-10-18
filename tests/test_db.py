import sqlite3
from pathlib import Path

import pytest

from core.memory.db import (
    CourseError,
    Courses,
    DuplicateCourse,
    Manifest,
    ResourceRow,
    SchemaError,
    connect,
    schema_version,
)
from core.memory.schema import SCHEMA_VERSION


def row(**overrides) -> ResourceRow:
    base = dict(
        resource_id="r10",
        course="CSE220",
        title="Lecture 1",
        added_at="2026-09-23T12:00:00+00:00",
    )
    return ResourceRow(**{**base, **overrides})


def test_upsert_round_trips_and_updates(tmp_path):
    manifest = Manifest(connect(tmp_path / "db" / "bl.db"))
    manifest.upsert(row())
    manifest.upsert(
        row(sync_state="synced", local_path="/x/lec1.pdf", filename="lec1.pdf", bucket="lectures")
    )

    got = manifest.get("r10")
    assert got.sync_state == "synced"
    assert got.local_path == "/x/lec1.pdf"
    assert manifest.find("CSE220", "lectures", "lec1.pdf") == got
    assert manifest.find("CSE220", "readings", "lec1.pdf") is None
    assert manifest.find("AMS161", "lectures", "lec1.pdf") is None
    assert len(manifest.all()) == 1


@pytest.mark.parametrize("state", ["deleted", "pending"])
def test_sync_state_is_constrained(state):
    manifest = Manifest(connect(":memory:"))
    with pytest.raises(sqlite3.IntegrityError):
        manifest.upsert(row(sync_state=state))


def test_model_runs_table_exists():
    conn = connect(":memory:")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(model_runs)")}
    assert {"run_id", "provider", "task_type", "success", "fallback_from"} <= cols


def test_all_filters_by_course_and_state():
    manifest = Manifest(connect(":memory:"))
    manifest.upsert(row(resource_id="b", sync_state="synced"))
    manifest.upsert(row(resource_id="a", sync_state="stale"))
    manifest.upsert(row(resource_id="c", course="AMS161", sync_state="synced"))
    manifest.upsert(row(resource_id="0", added_at="2026-09-24T09:00:00+00:00"))
    # oldest first, then by id
    assert [r.resource_id for r in manifest.all("CSE220", states=["synced", "stale"])] == [
        "a",
        "b",
        "0",
    ]
    assert [r.resource_id for r in manifest.all(states=["synced"])] == ["b", "c", "0"]


def test_courses_add_get_all():
    courses = Courses(connect(":memory:"), now=lambda: "2026-10-17T12:00:00+00:00")
    cse = courses.add("CSE220", "Systems Fundamentals", "Fall-2026")
    courses.add("AMS161", "Applied Calculus II", "Fall-2026")

    assert courses.get("CSE220") == cse
    assert cse.created_at == "2026-10-17T12:00:00+00:00"
    assert courses.get("CSE999") is None
    assert [c.course for c in courses.all()] == ["AMS161", "CSE220"]
    assert cse.root(Path("/data/courses")) == Path("/data/courses/Fall-2026/CSE220")


def test_courses_refuse_a_duplicate():
    courses = Courses(connect(":memory:"))
    courses.add("CSE220", "Systems Fundamentals", "Fall-2026")
    with pytest.raises(DuplicateCourse):
        courses.add("CSE220", "Again", "Spring-2027")
    assert courses.get("CSE220").term == "Fall-2026"


def test_a_duplicate_that_slips_past_the_check_is_still_a_duplicate(monkeypatch):
    """Another writer can add the course between ``get`` and the INSERT."""
    courses = Courses(connect(":memory:"))
    courses.add("CSE220", "Systems Fundamentals", "Fall-2026")
    monkeypatch.setattr(courses, "get", lambda course: None)
    with pytest.raises(DuplicateCourse) as raised:
        courses.add("CSE220", "Again", "Spring-2027")
    assert isinstance(raised.value.__cause__, sqlite3.IntegrityError)
    assert [(c.name, c.term) for c in courses.all()] == [("Systems Fundamentals", "Fall-2026")]


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("Linear Algebra", "LINEAR-ALGEBRA"),
        ("Álgebra lineal", "ALGEBRA-LINEAL"),
        ("CSE220", "CSE220"),
        ("  Intro to (Systems) / Networks!  ", "INTRO-TO-SYSTEMS-NETWORKS"),
        ("!!!", "COURSE"),
        ("Aux", "AUX-2"),  # a Windows device name is treated as taken
        ("Systems Fundamentals and Architecture of Computers", "SYSTEMS-FUNDAMENTALS-AND-ARC"),
    ],
)
def test_code_for_is_the_upper_cased_slug_of_the_name(name, code):
    courses = Courses(connect(":memory:"))
    assert courses.code_for(name) == code
    courses.add(courses.code_for(name), name, "Fall-2026")  # always a legal folder name


def test_code_for_dedupes_against_the_table():
    courses = Courses(connect(":memory:"))
    long = "Systems Fundamentals and Architecture of Computers"
    for _ in range(3):
        courses.add(courses.code_for("Linear Algebra"), "Linear Algebra", "Fall-2026")
        courses.add(courses.code_for(long), long, "Fall-2026")
    codes = [c.course for c in courses.all()]
    assert sorted(c for c in codes if c.startswith("LINEAR")) == [
        "LINEAR-ALGEBRA",
        "LINEAR-ALGEBRA-2",
        "LINEAR-ALGEBRA-3",
    ]
    assert sorted(c for c in codes if c.startswith("SYSTEMS")) == [
        "SYSTEMS-FUNDAMENTALS-AND-ARC",
        "SYSTEMS-FUNDAMENTALS-AND-ARC-2",
        "SYSTEMS-FUNDAMENTALS-AND-ARC-3",
    ]
    assert all(len(c) <= 32 for c in codes)


def test_find_is_deterministic_with_a_duplicate_name():
    """Rows from before v13 could share a name in a bucket; the oldest one wins."""
    manifest = Manifest(connect(":memory:"))
    for rid, added in [("b", "2026-09-02"), ("a", "2026-09-03"), ("c", "2026-09-01")]:
        manifest.upsert(row(resource_id=rid, added_at=added, bucket="lectures", filename="x.pdf"))
    assert manifest.find("CSE220", "lectures", "x.pdf").resource_id == "c"


@pytest.mark.parametrize(
    ("code", "term"),
    [
        ("", "Fall-2026"),
        ("CSE 220", "Fall-2026"),
        ("aux", "Fall-2026"),  # a Windows device name
        ("CSE220", "NUL"),
        ("../x", "Fall-2026"),
        ("X" * 33, "Fall-2026"),
        ("CSE220", "../up"),
        ("CSE220", "Fall/2026"),
    ],
)
def test_courses_refuse_codes_and_terms_that_are_not_folder_names(code, term):
    courses = Courses(connect(":memory:"))
    with pytest.raises(CourseError) as refused:
        courses.add(code, "Name", term)
    assert courses.all() == []
    # Which input to fix, so the web dialog can put the message under it.
    assert getattr(refused.value, "field", None) == ("term" if code == "CSE220" else "course")


LEGACY = """CREATE TABLE resources (course TEXT, org_unit_id INTEGER, topic_id INTEGER PRIMARY KEY,
    module_path TEXT, title TEXT, type_identifier TEXT, drive_file_id TEXT, drive_bucket TEXT,
    sync_state TEXT, last_seen TEXT)"""


def test_new_database_is_at_current_schema_version(tmp_path):
    assert schema_version(connect(tmp_path / "bl.db")) == SCHEMA_VERSION


def test_reconnect_does_not_rerun_migrations(tmp_path):
    connect(tmp_path / "bl.db").close()
    assert schema_version(connect(tmp_path / "bl.db")) == SCHEMA_VERSION


def test_empty_drive_era_manifest_is_replaced(tmp_path):
    path = tmp_path / "bl.db"
    legacy = sqlite3.connect(path)
    legacy.execute(LEGACY)
    legacy.commit()
    legacy.close()

    conn = connect(path)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(resources)")}
    assert "local_path" in cols and "drive_file_id" not in cols


def test_non_empty_drive_era_manifest_is_refused(tmp_path):
    path = tmp_path / "bl.db"
    legacy = sqlite3.connect(path)
    legacy.execute(LEGACY)
    legacy.execute("INSERT INTO resources (topic_id, drive_file_id) VALUES (1, 'd1')")
    legacy.commit()
    legacy.close()

    with pytest.raises(SchemaError, match="1 Drive-era"):
        connect(path)


def test_newer_schema_is_refused(tmp_path):
    path = tmp_path / "bl.db"
    future = sqlite3.connect(path)
    future.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    future.close()
    with pytest.raises(SchemaError):
        connect(path)
