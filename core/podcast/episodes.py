"""The ``podcasts`` table: which concepts each generated episode targeted (BL-034)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.ledger.ledger import utcnow


@dataclass(frozen=True)
class Episode:
    id: int
    course: str
    concepts: list[str]
    instruction_path: str
    audio_path: str
    created_at: str


class PodcastStore:
    def __init__(self, conn: sqlite3.Connection, now: Callable[[], str] = utcnow) -> None:
        self.conn = conn
        self._now = now

    def record(
        self, course: str, concept_ids: list[str], instruction_path: Path, audio_path: Path
    ) -> Episode:
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO podcasts (course, concepts, instruction_path, audio_path, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    course,
                    json.dumps(concept_ids),
                    str(instruction_path),
                    str(audio_path),
                    self._now(),
                ),
            )
        row = self.conn.execute(
            "SELECT * FROM podcasts WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return Episode(**{**dict(row), "concepts": json.loads(row["concepts"])})

    def get(self, episode_id: int) -> Episode | None:
        row = self.conn.execute("SELECT * FROM podcasts WHERE id = ?", (episode_id,)).fetchone()
        return Episode(**{**dict(row), "concepts": json.loads(row["concepts"])}) if row else None

    def all(self, course: str | None = None) -> list[Episode]:
        sql, args = "SELECT * FROM podcasts", []
        if course is not None:
            sql += " WHERE course = ?"
            args.append(course)
        rows = self.conn.execute(sql + " ORDER BY id", args)
        return [Episode(**{**dict(r), "concepts": json.loads(r["concepts"])}) for r in rows]
