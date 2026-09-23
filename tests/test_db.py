import sqlite3

import pytest

from core.memory.db import Manifest, ResourceRow, SchemaError, connect, schema_version
from core.memory.schema import SCHEMA_VERSION


def row(**overrides) -> ResourceRow:
    base = dict(
        course="CSE220",
        org_unit_id=1,
        topic_id=10,
        module_path="Week 1",
        title="Lecture 1",
        type_identifier="File",
        last_seen="2026-09-23T12:00:00+00:00",
    )
    return ResourceRow(**{**base, **overrides})


def test_upsert_round_trips_and_updates(tmp_path):
    manifest = Manifest(connect(tmp_path / "db" / "bl.db"))
    manifest.upsert(row())
    manifest.upsert(
        row(sync_state="synced", local_path="/x/lec1.pdf", filename="lec1.pdf", bucket="lectures")
    )

    got = manifest.get(10)
    assert got.sync_state == "synced"
    assert got.local_path == "/x/lec1.pdf"
    assert manifest.name_owner("CSE220", "lectures", "lec1.pdf") == 10
    assert len(manifest.all()) == 1


def test_sync_state_is_constrained():
    manifest = Manifest(connect(":memory:"))
    with pytest.raises(sqlite3.IntegrityError):
        manifest.upsert(row(sync_state="deleted"))


def test_model_runs_table_exists():
    conn = connect(":memory:")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(model_runs)")}
    assert {"run_id", "provider", "task_type", "success", "fallback_from"} <= cols


def test_all_filters_by_course_and_state():
    manifest = Manifest(connect(":memory:"))
    manifest.upsert(row(topic_id=1, sync_state="synced"))
    manifest.upsert(row(topic_id=2, sync_state="stale"))
    manifest.upsert(row(topic_id=3, course="AMS161", sync_state="synced"))
    assert [r.topic_id for r in manifest.all("CSE220", states=["synced", "stale"])] == [1, 2]
    assert [r.topic_id for r in manifest.all(states=["synced"])] == [1, 3]


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
