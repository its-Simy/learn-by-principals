"""The ``model_runs`` ledger: every model and NotebookLM call, logged locally (principle 10)."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.providers.models.base import ModelResult, TaskPackage


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

    @classmethod
    def from_result(
        cls,
        task: TaskPackage,
        result: ModelResult,
        started_at: str,
        fallback_from: str | None = None,
    ) -> ModelRun:
        hint = result.usage_hint
        return cls(
            provider=result.provider,
            model=result.model,
            task_type=task.task_type,
            persona=task.persona,
            started_at=started_at,
            duration_ms=result.duration_ms,
            success=True,
            input_tokens_est=(hint and hint.input_tokens)
            or estimate_tokens(task.system + task.user),
            output_tokens_est=(hint and hint.output_tokens) or estimate_tokens(result.text),
            fallback_from=fallback_from,
        )

    @classmethod
    def from_error(
        cls,
        task: TaskPackage,
        provider: str,
        error: BaseException,
        started_at: str,
        duration_ms: int,
        fallback_from: str | None = None,
    ) -> ModelRun:
        return cls(
            provider=provider,
            task_type=task.task_type,
            persona=task.persona,
            started_at=started_at,
            duration_ms=duration_ms,
            success=False,
            input_tokens_est=estimate_tokens(task.system + task.user),
            fallback_from=fallback_from,
            error=f"{type(error).__name__}: {error}",
        )


@dataclass(frozen=True)
class ProviderSummary:
    provider: str
    runs: int
    failures: int
    duration_ms: int
    input_tokens_est: int
    output_tokens_est: int


_COLUMNS = [f.name for f in fields(ModelRun)]


class Ledger:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def record(self, run: ModelRun) -> None:
        row = asdict(run)
        row["success"] = int(run.success)
        with self._conn:
            self._conn.execute(
                f"INSERT INTO model_runs ({', '.join(_COLUMNS)})"
                f" VALUES ({', '.join(':' + c for c in _COLUMNS)})",
                row,
            )

    def today_summary(self, now: datetime | None = None) -> list[ProviderSummary]:
        """Per-provider totals for runs started on ``now``'s UTC date."""
        day = (now or datetime.now(UTC)).astimezone(UTC).date().isoformat()
        rows = self._conn.execute(
            "SELECT provider, count(*), sum(1 - success), coalesce(sum(duration_ms), 0),"
            " coalesce(sum(input_tokens_est), 0), coalesce(sum(output_tokens_est), 0)"
            " FROM model_runs WHERE substr(started_at, 1, 10) = ? GROUP BY provider"
            " ORDER BY provider",
            (day,),
        )
        return [ProviderSummary(*row) for row in rows]
