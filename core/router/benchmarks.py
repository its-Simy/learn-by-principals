"""Measured model strengths per provider and task type (principle 8).

Samples are appended to ``benchmark_samples``; the ``benchmarks`` view averages them. The router
records ``format_compliance`` and ``latency_ms`` on every run; the Critic and the Analyzer's
excerpt check add ``accuracy`` and ``groundedness``; ``/rate`` in the tutor adds
``learner_rating``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from core.ledger.ledger import utcnow
from core.memory.schema import BENCHMARK_METRICS

# The composite score's weights. Missing metrics are left out and the rest re-weighted.
WEIGHTS = {"accuracy": 0.4, "groundedness": 0.3, "format_compliance": 0.3}


@dataclass(frozen=True)
class Benchmark:
    provider: str
    task_type: str
    accuracy: float | None
    groundedness: float | None
    format_compliance: float | None
    latency_ms: float | None
    learner_rating: float | None
    sample_count: int

    @property
    def score(self) -> float | None:
        """accuracy 0.4, groundedness 0.3, format_compliance 0.3, over the metrics measured."""
        present = {k: w for k, w in WEIGHTS.items() if getattr(self, k) is not None}
        if not present:
            return None
        return sum(getattr(self, k) * w for k, w in present.items()) / sum(present.values())


class Benchmarks:
    def __init__(self, conn: sqlite3.Connection, now: Callable[[], str] = utcnow) -> None:
        self.conn = conn
        self._now = now

    def record(self, provider: str, task_type: str, **metrics: float | None) -> None:
        unknown = set(metrics) - set(BENCHMARK_METRICS)
        if unknown:
            raise ValueError(f"Unknown benchmark metric(s) {sorted(unknown)}")
        rows = [
            (provider, task_type, metric, float(value), self._now())
            for metric, value in metrics.items()
            if value is not None
        ]
        with self.conn:
            self.conn.executemany(
                "INSERT INTO benchmark_samples (provider, task_type, metric, value, recorded_at)"
                " VALUES (?, ?, ?, ?, ?)",
                rows,
            )

    def for_task(self, task_type: str) -> dict[str, Benchmark]:
        rows = self.conn.execute("SELECT * FROM benchmarks WHERE task_type = ?", (task_type,))
        return {r["provider"]: Benchmark(**dict(r)) for r in rows}

    def all(self) -> list[Benchmark]:
        rows = self.conn.execute("SELECT * FROM benchmarks ORDER BY task_type, provider")
        return [Benchmark(**dict(r)) for r in rows]
