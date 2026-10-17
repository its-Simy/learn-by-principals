"""BL-040: migrations are sequential, one file each, never edited, and apply cleanly v0 -> now."""

import hashlib
import sqlite3
from pathlib import Path

import pytest

from core.memory.db import connect, schema_version
from core.memory.migrations import MIGRATIONS, SCHEMA_VERSION

# The checksum of every committed migration. Editing a committed migration fails this test;
# a new migration fails it until its checksum is added here (and then it is frozen too).
COMMITTED = {
    1: "738debec3ef5f4e81102fa07763cfb832d5663f5bf57e7260f7a191d3777fb51",
    2: "8930ccdd453fb19eb1cbaee58f98830dbefe936d78bb86d059210fd5bc6ab6bf",
    3: "1d9eb538cb3a72c188b88aa5edd365683aaebc23e15929fe2b51fcbe1029ef57",
    4: "2a757793d3e371bceb9be5690f607b72b30034049fe0004cd955c3c46e289de6",
    5: "9ab7a0ae86228505f42a9493694ac0a4db942e3b415f13b18a422648c6d8a55f",
    6: "024d37446dc1f40b47e14a4da8114f161779c45c048303203f79127e73d8d3ca",
    7: "83c567cbca25ea7e16c3e0b4af6bb76df5f309e7e21301e3ecec31f3d025e6fb",
    8: "a5d37e225152d2ec56a6b4cb04e47501cc9436d9018a5c14a8797d7c2e7ddb27",
    9: "0c7355784c2da3ff8b07d268d5d79e88ef770bacf57ca7007dbb4d0fd9660e9a",
    10: "f15ac3cb3e86efc32786f7e26bcf39ca01738bf6924e8d503230b2f105b321fb",
    11: "d9c5501ff50e36201d5e1e5be745a2562f7bb1d2291d6b3fa08c9cce3b6d8969",
    12: "cb5392875ae6b17001bbacb6db5e7ae2c7781782aad0d00d9564e17abd87f724",
    13: "ebfb92c00beba20ec4413441b4d9ccd701610e3d3fb11c7b0c68a921c08c00a6",
}
FOLDER = Path(__file__).parent.parent / "core" / "memory" / "migrations"
TABLES = {
    "resources",
    "model_runs",
    "notebooks",
    "concepts",
    "mastery",
    "evidence",
    "sessions",
    "mastery_history",
    "challenges",
    "podcasts",
    "benchmark_samples",
    "provider_health",
    "maintenance_runs",
    "courses",
}


def checksum(statements) -> str:
    return hashlib.sha256("\n;\n".join(statements).encode()).hexdigest()


def test_numbers_are_sequential_one_file_each():
    files = sorted(p.stem for p in FOLDER.glob("v*.py"))
    assert [int(f[1:4]) for f in files] == list(range(1, len(files) + 1))
    assert list(MIGRATIONS) == list(range(1, SCHEMA_VERSION + 1))
    assert len(files) == SCHEMA_VERSION


@pytest.mark.parametrize("number", sorted(MIGRATIONS))
def test_committed_migrations_are_never_edited(number):
    assert number in COMMITTED, f"record migration {number}'s checksum in COMMITTED"
    assert checksum(MIGRATIONS[number]) == COMMITTED[number], f"migration {number} was edited"


def test_migrations_apply_cleanly_from_v0_on_an_empty_database(tmp_path):
    path = tmp_path / "fresh.db"
    conn = connect(path)
    assert schema_version(conn) == SCHEMA_VERSION
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert TABLES <= names
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.execute("SELECT * FROM benchmarks").fetchall()  # the view works
    conn.close()
    assert schema_version(connect(path)) == SCHEMA_VERSION  # re-opening changes nothing


def test_each_step_applies_in_order(tmp_path):
    conn = sqlite3.connect(tmp_path / "steps.db")
    for number, statements in MIGRATIONS.items():
        with conn:
            for statement in statements:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {number}")
        assert conn.execute("PRAGMA user_version").fetchone()[0] == number


def test_v9_keeps_every_history_row_and_the_append_only_guard(tmp_path):
    path = tmp_path / "v8.db"
    raw = sqlite3.connect(path)
    for number in range(1, 9):
        with raw:
            for statement in MIGRATIONS[number]:
                raw.execute(statement)
            raw.execute(f"PRAGMA user_version = {number}")
    with raw:
        raw.execute("INSERT INTO concepts (concept_id, course, name) VALUES ('c/x', 'C', 'X')")
        for level in (1, 2):
            raw.execute(
                "INSERT INTO mastery_history (concept_id, old_level, new_level, confidence,"
                " evidence_ids, changed_at, changed_by) VALUES ('c/x', ?, ?, 0.5, '[]', 't',"
                " 'analyzer')",
                (level - 1, level),
            )
    raw.close()

    conn = connect(path)  # v8 -> current

    rows = conn.execute("SELECT id, new_level FROM mastery_history ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [(1, 1), (2, 2)]
    with conn:
        conn.execute(
            "INSERT INTO mastery_history (concept_id, new_level, confidence, evidence_ids,"
            " changed_at, changed_by) VALUES ('c/x', 3, 0.8, '[]', 't', 'challenger')"
        )
    assert conn.execute("SELECT max(id) FROM mastery_history").fetchone()[0] == 3
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM mastery_history")
    assert conn.execute("SELECT status FROM concepts").fetchone()[0] == "active"


def test_v13_keys_resources_by_id_and_backfills_courses(tmp_path):
    path = tmp_path / "v12.db"
    raw = sqlite3.connect(path)
    for number in range(1, 13):
        with raw:
            for statement in MIGRATIONS[number]:
                raw.execute(statement)
            raw.execute(f"PRAGMA user_version = {number}")
    root = "/home/s/.brightlearn/courses/Fall-2026/CSE220"
    rows = [
        # topic_id, course, title, type, url, filename, local_path, hash, source id, state, seen
        (
            5001,
            "CSE220",
            "Syllabus",
            "File",
            None,
            "syl.pdf",
            f"{root}/syllabus/syl.pdf",
            "h1",
            "src1",
            "synced",
            "2026-09-23T12:00:00+00:00",
        ),
        (
            5002,
            "CSE220",
            "Lecture 1",
            "File",
            None,
            "lec1.pdf",
            f"{root}/lectures/lec1.pdf",
            "h2",
            None,
            "stale",
            "2026-09-22T12:00:00+00:00",
        ),
        (
            5004,
            "CSE220",
            "Zoom",
            "Link",
            "https://zoom.example/rec",
            None,
            None,
            None,
            None,
            "link",
            "2026-09-24T12:00:00+00:00",
        ),
        (
            6001,
            "AMS161",
            "Lecture 1",
            "File",
            None,
            None,
            None,
            None,
            None,
            "pending",
            "2026-09-25T12:00:00+00:00",
        ),
        (  # a stored file whose path has no "/MAT125/" segment: the term can't be read
            7001,
            "MAT125",
            "Notes",
            "File",
            None,
            "notes.pdf",
            "/elsewhere/notes.pdf",
            "h3",
            None,
            "synced",
            "2026-09-26T12:00:00+00:00",
        ),
    ]
    with raw:
        raw.executemany(
            "INSERT INTO resources (topic_id, course, org_unit_id, module_path, title,"
            " type_identifier, url, filename, local_path, hash, notebook_source_id, sync_state,"
            " last_seen) VALUES (?, ?, 1, 'Week 1', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(r[0], r[1], *r[2:]) for r in rows],
        )
    raw.close()

    conn = connect(path)  # v12 -> current

    cols = [r["name"] for r in conn.execute("PRAGMA table_info(resources)")]
    assert cols[0] == "resource_id" and "added_at" in cols
    assert not {
        "topic_id",
        "org_unit_id",
        "module_path",
        "type_identifier",
        "last_modified",
        "last_seen",
    } & set(cols)
    got = {
        r["resource_id"]: dict(r)
        for r in conn.execute("SELECT * FROM resources ORDER BY resource_id")
    }
    assert list(got) == ["topic:5001", "topic:5002", "topic:5004", "topic:6001", "topic:7001"]
    syllabus = got["topic:5001"]
    assert (syllabus["local_path"], syllabus["hash"], syllabus["notebook_source_id"]) == (
        f"{root}/syllabus/syl.pdf",
        "h1",
        "src1",
    )
    assert syllabus["added_at"] == "2026-09-23T12:00:00+00:00"
    assert got["topic:5002"]["sync_state"] == "stale"
    link = got["topic:5004"]
    assert (link["sync_state"], link["url"], link["local_path"]) == (
        "link",
        "https://zoom.example/rec",
        None,
    )
    assert got["topic:6001"]["sync_state"] == "failed"  # pending had no file

    courses = [tuple(r) for r in conn.execute("SELECT * FROM courses ORDER BY course")]
    assert courses == [
        ("AMS161", "AMS161", "unknown", "2026-09-25T12:00:00+00:00"),
        ("CSE220", "CSE220", "Fall-2026", "2026-09-22T12:00:00+00:00"),
        ("MAT125", "MAT125", "unknown", "2026-09-26T12:00:00+00:00"),
    ]
    assert got["topic:7001"]["local_path"] == "/elsewhere/notes.pdf"  # the file is kept
    indexes = {r[1] for r in conn.execute("PRAGMA index_list(resources)")}
    assert "resources_course" in indexes
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO resources (resource_id, course, title, added_at, sync_state)"
            " VALUES ('x', 'CSE220', 'x', 't', 'pending')"
        )
