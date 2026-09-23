"""Learner memory: concepts, mastery, append-only evidence, tutoring sessions.

Mastery levels: 0 unseen, 1 exposed, 2 explained, 3 applied, 4 transferred, 5 retained.
Retention confidence decays with time since the last evidence; the level itself never decays.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime

from core.ledger.ledger import utcnow
from core.memory.schema import EVIDENCE_STRENGTHS, EVIDENCE_TYPES, MASTERY_CHANGERS

# Retention decay: untouched for GRACE_DAYS, then halves every HALF_LIFE_DAYS.
GRACE_DAYS = 2.0
HALF_LIFE_DAYS = 14.0


class LearnerError(Exception):
    pass


class MasteryWithoutEvidence(LearnerError):
    """Principle 4: a mastery score needs the evidence rows that justify it."""


@dataclass
class Concept:
    concept_id: str
    course: str
    name: str
    module: str | None = None
    prerequisites: list[str] = field(default_factory=list)
    exam_tags: list[str] = field(default_factory=list)


@dataclass
class Mastery:
    concept_id: str
    level: int = 0
    confidence: float = 0.0
    evidence_count: int = 0
    last_evidence_at: str | None = None
    retention_confidence: float | None = None
    last_reviewed: str | None = None


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    concept_id: str
    session_id: str | None
    type: str
    strength: str
    source_provider: str | None
    excerpt_ref: str | None
    recorded_at: str


@dataclass(frozen=True)
class MasteryChange:
    id: int
    concept_id: str
    old_level: int | None
    new_level: int
    confidence: float
    evidence_ids: list[str]
    changed_at: str
    changed_by: str


@dataclass
class SessionRow:
    session_id: str
    course: str
    started_at: str
    ended_at: str | None = None
    tutor_provider: str | None = None
    analyzer_provider: str | None = None
    summary_path: str | None = None


def _as_datetime(value: str | datetime) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def retention(confidence: float, days_since_evidence: float) -> float:
    if days_since_evidence <= GRACE_DAYS:
        return confidence
    return confidence * 0.5 ** ((days_since_evidence - GRACE_DAYS) / HALF_LIFE_DAYS)


def _concept(row: sqlite3.Row) -> Concept:
    return Concept(
        concept_id=row["concept_id"],
        course=row["course"],
        name=row["name"],
        module=row["module"],
        prerequisites=json.loads(row["prerequisites"]),
        exam_tags=json.loads(row["exam_tags"]),
    )


def _mastery(row: sqlite3.Row) -> Mastery:
    return Mastery(**{k: row[k] for k in Mastery.__dataclass_fields__})


class LearnerMemory:
    def __init__(self, conn: sqlite3.Connection, now: Callable[[], str] = utcnow) -> None:
        self.conn = conn
        self._now = now

    # -- concepts ----------------------------------------------------------------------------

    def upsert_concept(self, concept: Concept) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO concepts (concept_id, course, name, module, prerequisites, exam_tags)"
                " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (concept_id) DO UPDATE SET"
                " course = excluded.course, name = excluded.name, module = excluded.module,"
                " prerequisites = excluded.prerequisites, exam_tags = excluded.exam_tags",
                (
                    concept.concept_id,
                    concept.course,
                    concept.name,
                    concept.module,
                    json.dumps(concept.prerequisites),
                    json.dumps(concept.exam_tags),
                ),
            )

    def get_concept(self, concept_id: str) -> Concept | None:
        row = self.conn.execute(
            "SELECT * FROM concepts WHERE concept_id = ?", (concept_id,)
        ).fetchone()
        return _concept(row) if row else None

    def concepts(self, course: str) -> list[Concept]:
        rows = self.conn.execute(
            "SELECT * FROM concepts WHERE course = ? ORDER BY concept_id", (course,)
        )
        return [_concept(r) for r in rows]

    # -- mastery and evidence ----------------------------------------------------------------

    def get_mastery(self, concept_id: str) -> Mastery | None:
        row = self.conn.execute(
            "SELECT * FROM mastery WHERE concept_id = ?", (concept_id,)
        ).fetchone()
        return _mastery(row) if row else None

    def add_evidence(
        self,
        concept_id: str,
        type: str,
        strength: str,
        session_id: str | None = None,
        source_provider: str | None = None,
        excerpt_ref: str | None = None,
    ) -> str:
        if type not in EVIDENCE_TYPES:
            raise LearnerError(f"Evidence type {type!r} is not one of {EVIDENCE_TYPES}")
        if strength not in EVIDENCE_STRENGTHS:
            raise LearnerError(f"Evidence strength {strength!r} is not one of {EVIDENCE_STRENGTHS}")
        if self.get_concept(concept_id) is None:
            raise LearnerError(f"Unknown concept {concept_id!r}")
        evidence_id = uuid.uuid4().hex
        with self.conn:
            self.conn.execute(
                "INSERT INTO evidence (evidence_id, concept_id, session_id, type, strength,"
                " source_provider, excerpt_ref, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    evidence_id,
                    concept_id,
                    session_id,
                    type,
                    strength,
                    source_provider,
                    excerpt_ref,
                    self._now(),
                ),
            )
        return evidence_id

    def evidence(self, concept_id: str) -> list[Evidence]:
        rows = self.conn.execute(
            "SELECT * FROM evidence WHERE concept_id = ? ORDER BY recorded_at, rowid", (concept_id,)
        )
        return [Evidence(**dict(r)) for r in rows]

    def set_mastery(
        self,
        concept_id: str,
        level: int,
        confidence: float,
        evidence_ids: Iterable[str],
        changed_by: str = "manual",
    ) -> Mastery:
        """Set a concept's mastery, justified by ``evidence_ids`` (which must be this concept's).

        Every call also appends a ``mastery_history`` row naming those evidence ids.
        """
        evidence_ids = list(evidence_ids)
        if not evidence_ids:
            raise MasteryWithoutEvidence(f"set_mastery({concept_id!r}) needs evidence ids")
        if changed_by not in MASTERY_CHANGERS:
            raise LearnerError(f"changed_by {changed_by!r} is not one of {MASTERY_CHANGERS}")
        if not 0 <= level <= 5:
            raise LearnerError(f"Mastery level {level} is outside 0-5")
        if not 0.0 <= confidence <= 1.0:
            raise LearnerError(f"Confidence {confidence} is outside 0-1")
        marks = ", ".join("?" for _ in evidence_ids)
        found = {
            r["evidence_id"]
            for r in self.conn.execute(
                "SELECT evidence_id FROM evidence"
                f" WHERE concept_id = ? AND evidence_id IN ({marks})",
                (concept_id, *evidence_ids),
            )
        }
        missing = sorted(set(evidence_ids) - found)
        if missing:
            raise MasteryWithoutEvidence(f"Evidence {missing} doesn't exist for {concept_id!r}")
        count, last = self.conn.execute(
            "SELECT count(*), max(recorded_at) FROM evidence WHERE concept_id = ?", (concept_id,)
        ).fetchone()
        previous = self.get_mastery(concept_id)
        mastery = Mastery(
            concept_id=concept_id,
            level=level,
            confidence=confidence,
            evidence_count=count,
            last_evidence_at=last,
            retention_confidence=confidence,
            last_reviewed=self._now(),
        )
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO mastery (concept_id, level, confidence, evidence_count,"
                " last_evidence_at, retention_confidence, last_reviewed)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    mastery.concept_id,
                    mastery.level,
                    mastery.confidence,
                    mastery.evidence_count,
                    mastery.last_evidence_at,
                    mastery.retention_confidence,
                    mastery.last_reviewed,
                ),
            )
            self.conn.execute(
                "INSERT INTO mastery_history (concept_id, old_level, new_level, confidence,"
                " evidence_ids, changed_at, changed_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    concept_id,
                    previous.level if previous else None,
                    level,
                    confidence,
                    json.dumps(evidence_ids),
                    mastery.last_reviewed,
                    changed_by,
                ),
            )
        return mastery

    def mastery_history(self, concept_id: str) -> list[MasteryChange]:
        rows = self.conn.execute(
            "SELECT * FROM mastery_history WHERE concept_id = ? ORDER BY id", (concept_id,)
        )
        return [
            MasteryChange(**{**dict(r), "evidence_ids": json.loads(r["evidence_ids"])})
            for r in rows
        ]

    def weakest(
        self, course: str, n: int, exam_tag: str | None = None
    ) -> list[tuple[Concept, Mastery]]:
        """Lowest level first, then lowest retention, then lowest confidence. Unseen = level 0."""
        sql = (
            "SELECT c.*, m.level, m.confidence, m.evidence_count, m.last_evidence_at,"
            " m.retention_confidence, m.last_reviewed"
            " FROM concepts c LEFT JOIN mastery m ON m.concept_id = c.concept_id"
            " WHERE c.course = ?"
        )
        args: list[object] = [course]
        if exam_tag is not None:
            sql += " AND EXISTS (SELECT 1 FROM json_each(c.exam_tags) WHERE value = ?)"
            args.append(exam_tag)
        sql += (
            " ORDER BY coalesce(m.level, 0), coalesce(m.retention_confidence, 0),"
            " coalesce(m.confidence, 0), c.name LIMIT ?"
        )
        args.append(n)
        result = []
        for row in self.conn.execute(sql, args):
            mastery = Mastery(
                concept_id=row["concept_id"],
                level=row["level"] or 0,
                confidence=row["confidence"] or 0.0,
                evidence_count=row["evidence_count"] or 0,
                last_evidence_at=row["last_evidence_at"],
                retention_confidence=row["retention_confidence"],
                last_reviewed=row["last_reviewed"],
            )
            result.append((_concept(row), mastery))
        return result

    def decay_retention(self, now: str | datetime) -> int:
        """Recompute retention_confidence from time since the last evidence. Returns rows changed.

        Idempotent for a given ``now``: retention is derived from ``confidence``, not from its own
        previous value.
        """
        now_dt = _as_datetime(now)
        changed = 0
        rows = self.conn.execute(
            "SELECT concept_id, confidence, last_evidence_at, retention_confidence FROM mastery"
            " WHERE last_evidence_at IS NOT NULL"
        ).fetchall()
        with self.conn:
            for row in rows:
                days = (now_dt - _as_datetime(row["last_evidence_at"])).total_seconds() / 86400
                value = round(retention(row["confidence"], days), 6)
                if value != row["retention_confidence"]:
                    self.conn.execute(
                        "UPDATE mastery SET retention_confidence = ? WHERE concept_id = ?",
                        (value, row["concept_id"]),
                    )
                    changed += 1
        return changed

    # -- sessions ----------------------------------------------------------------------------

    def start_session(self, course: str, tutor_provider: str | None = None) -> SessionRow:
        started = self._now()
        session = SessionRow(
            session_id=f"{started[:16].replace(':', '')}-{uuid.uuid4().hex[:6]}",
            course=course,
            started_at=started,
            tutor_provider=tutor_provider,
        )
        with self.conn:
            self.conn.execute(
                "INSERT INTO sessions (session_id, course, started_at, tutor_provider)"
                " VALUES (?, ?, ?, ?)",
                (session.session_id, course, started, tutor_provider),
            )
        return session

    def update_session(self, session: SessionRow) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE sessions SET ended_at = ?, tutor_provider = ?, analyzer_provider = ?,"
                " summary_path = ? WHERE session_id = ?",
                (
                    session.ended_at,
                    session.tutor_provider,
                    session.analyzer_provider,
                    session.summary_path,
                    session.session_id,
                ),
            )

    def get_session(self, session_id: str) -> SessionRow | None:
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return SessionRow(**dict(row)) if row else None
