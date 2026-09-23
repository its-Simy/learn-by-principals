import sqlite3

import pytest

from core.memory.db import Manifest, ResourceRow, connect


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
        row(sync_state="synced", drive_file_id="abc", filename="lec1.pdf", drive_bucket="lectures")
    )

    got = manifest.get(10)
    assert got.sync_state == "synced"
    assert got.drive_file_id == "abc"
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
