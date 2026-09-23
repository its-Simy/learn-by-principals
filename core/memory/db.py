from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from core.memory.schema import MIGRATIONS, SCHEMA_VERSION

log = logging.getLogger(__name__)


class SchemaError(Exception):
    pass


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    migrate(conn)
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> None:
    version = schema_version(conn)
    if version > SCHEMA_VERSION:
        raise SchemaError(f"Database is at schema v{version}; this code knows v{SCHEMA_VERSION}")
    if version == 0:
        _drop_empty_legacy_manifest(conn)
    for target in sorted(v for v in MIGRATIONS if v > version):
        conn.execute("BEGIN")
        try:
            for statement in MIGRATIONS[target]:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {target}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        log.info("Database migrated to schema v%d", target)


def _drop_empty_legacy_manifest(conn: sqlite3.Connection) -> None:
    """The unversioned Drive-era ``resources`` table: dropped if empty, refused otherwise."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(resources)")}
    if "drive_file_id" not in cols:
        return
    count = conn.execute("SELECT count(*) FROM resources").fetchone()[0]
    if count:
        raise SchemaError(
            f"The database has {count} Drive-era manifest rows; there is no migration for them yet"
        )
    with conn:
        conn.execute("DROP TABLE resources")
    log.info("Dropped the empty Drive-era resources table")


@dataclass
class ResourceRow:
    course: str
    org_unit_id: int
    topic_id: int
    module_path: str
    title: str
    type_identifier: str
    last_seen: str
    url: str | None = None
    filename: str | None = None
    size: int | None = None
    last_modified: str | None = None
    hash: str | None = None
    local_path: str | None = None
    bucket: str | None = None
    notebook_id: str | None = None
    notebook_source_id: str | None = None
    source_hash: str | None = None
    sync_state: str = "pending"


_COLUMNS = [f.name for f in fields(ResourceRow)]


class Manifest:
    """The ``resources`` table: one row per Brightspace topic. Rows are never deleted."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, topic_id: int) -> ResourceRow | None:
        row = self.conn.execute(
            "SELECT * FROM resources WHERE topic_id = ?", (topic_id,)
        ).fetchone()
        return ResourceRow(**dict(row)) if row else None

    def upsert(self, row: ResourceRow) -> None:
        cols = ", ".join(_COLUMNS)
        marks = ", ".join(f":{c}" for c in _COLUMNS)
        updates = ", ".join(f"{c} = excluded.{c}" for c in _COLUMNS if c != "topic_id")
        with self.conn:
            self.conn.execute(
                f"INSERT INTO resources ({cols}) VALUES ({marks}) "
                f"ON CONFLICT (topic_id) DO UPDATE SET {updates}",
                asdict(row),
            )

    def name_owner(self, course: str, bucket: str, filename: str) -> int | None:
        """topic_id of the row already using ``filename`` in this course bucket, if any."""
        row = self.conn.execute(
            "SELECT topic_id FROM resources WHERE course = ? AND bucket = ? AND filename = ?",
            (course, bucket, filename),
        ).fetchone()
        return row["topic_id"] if row else None

    def all(
        self, course: str | None = None, states: Iterable[str] | None = None
    ) -> list[ResourceRow]:
        sql, args = "SELECT * FROM resources WHERE 1 = 1", []
        if course is not None:
            sql += " AND course = ?"
            args.append(course)
        if states is not None:
            states = list(states)
            sql += f" AND sync_state IN ({', '.join('?' for _ in states)})"
            args.extend(states)
        return [ResourceRow(**dict(r)) for r in self.conn.execute(sql + " ORDER BY topic_id", args)]
