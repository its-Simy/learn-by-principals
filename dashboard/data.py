"""What the usage dashboard shows, read from SQLite (principle 10: the ledger is the truth)."""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from core.memory.schema import SYNC_STATES
from core.router.benchmarks import Benchmark, Benchmarks
from core.router.health import HealthRecord, HealthStore

NOTEBOOKLM = "notebooklm"
ARTIFACT_TASKS = {
    "generate_audio": "Audio overviews",
    "generate_quiz": "Quizzes",
    "generate": "Other artifacts",
}
WEAKEST = 10


@dataclass(frozen=True)
class ProviderRuns:
    provider: str
    calls: int
    failures: int
    median_ms: int | None
    fallbacks: int


@dataclass(frozen=True)
class WeakConcept:
    course: str
    name: str
    level: int
    confidence: float
    retention: float | None


@dataclass
class DashboardData:
    generated_at: datetime
    today: list[ProviderRuns] = field(default_factory=list)
    week: list[ProviderRuns] = field(default_factory=list)
    health: list[HealthRecord] = field(default_factory=list)
    benchmarks: list[Benchmark] = field(default_factory=list)
    artifacts_week: dict[str, int] = field(default_factory=dict)
    artifacts_total: dict[str, int] = field(default_factory=dict)
    podcasts: int = 0
    sync: dict[str, dict[str, int]] = field(default_factory=dict)  # course -> state -> count
    weakest: list[WeakConcept] = field(default_factory=list)


def _runs(conn: sqlite3.Connection, since: str, until: str | None = None) -> list[ProviderRuns]:
    sql = (
        "SELECT provider, success, duration_ms, fallback_from FROM model_runs WHERE started_at >= ?"
    )
    args = [since]
    if until is not None:
        sql += " AND started_at < ?"
        args.append(until)
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in conn.execute(sql, args):
        grouped.setdefault(row["provider"], []).append(row)
    out = []
    for provider, rows in sorted(grouped.items()):
        durations = [r["duration_ms"] for r in rows if r["duration_ms"] is not None]
        out.append(
            ProviderRuns(
                provider=provider,
                calls=len(rows),
                failures=sum(1 for r in rows if not r["success"]),
                median_ms=int(statistics.median(durations)) if durations else None,
                fallbacks=sum(1 for r in rows if r["fallback_from"]),
            )
        )
    return out


def _artifacts(conn: sqlite3.Connection, since: str | None) -> dict[str, int]:
    sql = (
        "SELECT task_type, count(*) FROM model_runs WHERE provider = ? AND success = 1"
        f" AND task_type IN ({', '.join('?' for _ in ARTIFACT_TASKS)})"
    )
    args: list[object] = [NOTEBOOKLM, *ARTIFACT_TASKS]
    if since is not None:
        sql += " AND started_at >= ?"
        args.append(since)
    counts = dict(conn.execute(sql + " GROUP BY task_type", args).fetchall())
    return {label: counts.get(task, 0) for task, label in ARTIFACT_TASKS.items()}


def collect(conn: sqlite3.Connection, now: datetime | None = None) -> DashboardData:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
    week = (now - timedelta(days=7)).isoformat(timespec="seconds")
    data = DashboardData(generated_at=now)
    data.today = _runs(conn, day)
    data.week = _runs(conn, week)
    data.health = HealthStore(conn).all()
    data.benchmarks = Benchmarks(conn).all()
    data.artifacts_week = _artifacts(conn, week)
    data.artifacts_total = _artifacts(conn, None)
    data.podcasts = conn.execute("SELECT count(*) FROM podcasts").fetchone()[0]
    for course, state, count in conn.execute(
        "SELECT course, sync_state, count(*) FROM resources GROUP BY course, sync_state"
    ):
        data.sync.setdefault(course, dict.fromkeys(SYNC_STATES, 0))[state] = count
    rows = conn.execute(
        "SELECT c.course, c.name, coalesce(m.level, 0) AS level,"
        " coalesce(m.confidence, 0) AS confidence, m.retention_confidence AS retention"
        " FROM concepts c LEFT JOIN mastery m ON m.concept_id = c.concept_id"
        " WHERE c.status = 'active'"
        " ORDER BY level, coalesce(m.retention_confidence, 0), confidence, c.name LIMIT ?",
        (WEAKEST,),
    )
    data.weakest = [WeakConcept(**dict(r)) for r in rows]
    return data
