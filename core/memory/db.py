from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from core.memory.schema import STATEMENTS


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    with conn:
        for statement in STATEMENTS:
            conn.execute(statement)
    return conn


@dataclass
class ResourceRow:
    course: str
    org_unit_id: int
    topic_id: int
    module_path: str
    title: str
    type_identifier: str
    last_seen: str
    filename: str | None = None
    size: int | None = None
    last_modified: str | None = None
    hash: str | None = None
    drive_file_id: str | None = None
    drive_bucket: str | None = None
    notebook_id: str | None = None
    notebook_source_id: str | None = None
    sync_state: str = "pending"


_COLUMNS = [f.name for f in fields(ResourceRow)]


class Manifest:
    """The ``resources`` table: one row per Brightspace topic. Rows are never deleted."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, topic_id: int) -> ResourceRow | None:
        row = self._conn.execute(
            "SELECT * FROM resources WHERE topic_id = ?", (topic_id,)
        ).fetchone()
        return ResourceRow(**dict(row)) if row else None

    def upsert(self, row: ResourceRow) -> None:
        cols = ", ".join(_COLUMNS)
        marks = ", ".join(f":{c}" for c in _COLUMNS)
        updates = ", ".join(f"{c} = excluded.{c}" for c in _COLUMNS if c != "topic_id")
        with self._conn:
            self._conn.execute(
                f"INSERT INTO resources ({cols}) VALUES ({marks}) "
                f"ON CONFLICT (topic_id) DO UPDATE SET {updates}",
                asdict(row),
            )

    def name_owner(self, course: str, bucket: str, filename: str) -> int | None:
        """topic_id of the row already using ``filename`` in this course bucket, if any."""
        row = self._conn.execute(
            "SELECT topic_id FROM resources WHERE course = ? AND drive_bucket = ? AND filename = ?",
            (course, bucket, filename),
        ).fetchone()
        return row["topic_id"] if row else None

    def all(self, course: str | None = None) -> list[ResourceRow]:
        if course is None:
            rows = self._conn.execute("SELECT * FROM resources ORDER BY topic_id")
        else:
            rows = self._conn.execute(
                "SELECT * FROM resources WHERE course = ? ORDER BY topic_id", (course,)
            )
        return [ResourceRow(**dict(r)) for r in rows]
