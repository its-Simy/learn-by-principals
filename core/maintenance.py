"""``brightlearn maintain`` (BL-038): decay retention, close idle sessions, archive old ones, and
log the run.

Every other command runs it first when the last run is more than ``EVERY`` ago.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.memory.learner import HALF_LIFE_DAYS, LearnerMemory, RetentionChange, idle_for
from core.memory.vault import Vault

log = logging.getLogger(__name__)

EVERY = timedelta(hours=24)
ARCHIVE_AFTER = timedelta(days=30)
STALE_AFTER = timedelta(hours=2)  # `ask` calls an open session this idle stale (BL-040)
CLOSE_IDLE_AFTER = timedelta(hours=24)  # `maintain` closes an open session this idle


@dataclass
class MaintenanceReport:
    ran_at: datetime
    decayed: list[RetentionChange] = field(default_factory=list)
    archived: list[str] = field(default_factory=list)  # session ids
    closed: list[str] = field(default_factory=list)  # idle open sessions closed


def _now() -> datetime:
    return datetime.now(UTC)


def last_run(conn: sqlite3.Connection) -> datetime | None:
    value = conn.execute("SELECT max(ran_at) FROM maintenance_runs").fetchone()[0]
    return datetime.fromisoformat(value) if value else None


def due(conn: sqlite3.Connection, now: datetime) -> bool:
    last = last_run(conn)
    return last is None or now - last >= EVERY


def maintain(
    conn: sqlite3.Connection,
    vault_root: Path,
    now: datetime | None = None,
    half_life_days: float = HALF_LIFE_DAYS,
    trigger: str = "manual",
) -> MaintenanceReport:
    now = now or _now()
    report = MaintenanceReport(now)
    learner = LearnerMemory(conn)
    report.decayed = learner.decay_retention(now, half_life_days, fresh_since=last_run(conn))
    report.closed = close_idle_sessions(learner, now)
    report.archived = archive_sessions(learner, Vault(vault_root), now)
    with conn:
        conn.execute(
            "INSERT INTO maintenance_runs (ran_at, trigger, decayed, archived, closed)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                now.isoformat(timespec="seconds"),
                trigger,
                len(report.decayed),
                len(report.archived),
                len(report.closed),
            ),
        )
    return report


def maybe_maintain(
    conn: sqlite3.Connection,
    vault_root: Path,
    half_life_days: float = HALF_LIFE_DAYS,
    now: Callable[[], datetime] = _now,
) -> MaintenanceReport | None:
    """Run maintenance if it hasn't run in the last 24 hours."""
    moment = now()
    if not due(conn, moment):
        return None
    return maintain(conn, vault_root, moment, half_life_days, trigger="auto")


def close_idle_sessions(learner: LearnerMemory, now: datetime) -> list[str]:
    """Close open sessions with no turn for ``CLOSE_IDLE_AFTER``. The Analyzer isn't run."""
    closed = []
    for session in learner.open_sessions():
        if idle_for(session, now) > CLOSE_IDLE_AFTER:
            learner.close_session(session.session_id, now)
            closed.append(session.session_id)
    return closed


def archive_sessions(learner: LearnerMemory, vault: Vault, now: datetime) -> list[str]:
    """Move ended sessions older than ``ARCHIVE_AFTER`` into ``vault/sessions/archive/``.

    Files are moved, never deleted (principle 3); ``summary_path`` follows the summary.
    """
    cutoff = now - ARCHIVE_AFTER
    archive = vault.root / "sessions" / "archive"
    moved = []
    for session in learner.sessions():
        if session.ended_at is None or datetime.fromisoformat(session.started_at) >= cutoff:
            continue
        paths = [
            vault.session_transcript_path(session.session_id),
            vault.session_summary_path(session.session_id),
        ]
        if not any(p.exists() for p in paths):
            continue  # already archived (or never written)
        archive.mkdir(parents=True, exist_ok=True)
        for path in paths:
            if path.exists():
                shutil.move(path, archive / path.name)
        if session.summary_path and Path(session.summary_path).parent != archive:
            session.summary_path = str(archive / Path(session.summary_path).name)
            learner.update_session(session)
        moved.append(session.session_id)
    return moved
