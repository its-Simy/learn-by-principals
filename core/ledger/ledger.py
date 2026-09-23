"""The ``model_runs`` ledger: every model and NotebookLM call, logged locally (principle 10)."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def estimate_tokens(text: str | None) -> int:
    """Rough count (4 characters per token); good enough for a usage ledger."""
    return (len(text) + 3) // 4 if text else 0


@dataclass
class ModelRun:
    provider: str
    task_type: str
    started_at: str
    success: bool
    model: str | None = None
    persona: str | None = None
    duration_ms: int | None = None
    input_tokens_est: int | None = None
    output_tokens_est: int | None = None
    fallback_from: str | None = None
    error: str | None = None
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)


_COLUMNS = [f.name for f in fields(ModelRun)]


class Ledger:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(self, run: ModelRun) -> None:
        row = asdict(run)
        row["success"] = int(run.success)
        with self._conn:
            self._conn.execute(
                f"INSERT INTO model_runs ({', '.join(_COLUMNS)})"
                f" VALUES ({', '.join(':' + c for c in _COLUMNS)})",
                row,
            )
