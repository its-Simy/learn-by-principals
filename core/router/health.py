"""The router's record of each provider's health, kept in ``provider_health`` so a rate-limit
cooldown survives from one command to the next."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from core.providers.models.base import UsageHint
from core.providers.state import ProviderState

DEFAULT_COOLDOWN = timedelta(minutes=60)
_IN = re.compile(r"\bin\s+(\d+)\s*(min|minute|minutes|h|hr|hour|hours)\b", re.IGNORECASE)


@dataclass(frozen=True)
class HealthRecord:
    provider: str
    state: ProviderState
    checked_at: datetime
    cooldown_until: datetime | None
    detail: str | None


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def cooldown_until(hint: UsageHint | None, now: datetime) -> datetime:
    """When a rate limit ends: the hint's ``resets_at`` if it's a future time we can read
    (ISO timestamp, epoch seconds, or "in N minutes/hours"), else ``DEFAULT_COOLDOWN`` from now."""
    text = (hint.resets_at if hint else None) or ""
    until: datetime | None = None
    try:
        until = _parse(text.strip()) if text.strip() else None
    except ValueError:
        if text.strip().isdigit():
            until = datetime.fromtimestamp(int(text.strip()), UTC)
        elif match := _IN.search(text):
            n, unit = int(match.group(1)), match.group(2).lower()
            until = now + (timedelta(minutes=n) if unit.startswith("m") else timedelta(hours=n))
    if until is None or until <= now:
        return now + DEFAULT_COOLDOWN
    return until


class HealthStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, provider: str) -> HealthRecord | None:
        row = self.conn.execute(
            "SELECT * FROM provider_health WHERE provider = ?", (provider,)
        ).fetchone()
        return self._record(row) if row else None

    def set(
        self,
        provider: str,
        state: ProviderState,
        now: datetime,
        cooldown: datetime | None = None,
        detail: str | None = None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO provider_health (provider, state, checked_at, cooldown_until, detail)"
                " VALUES (?, ?, ?, ?, ?) ON CONFLICT (provider) DO UPDATE SET"
                " state = excluded.state, checked_at = excluded.checked_at,"
                " cooldown_until = excluded.cooldown_until, detail = excluded.detail",
                (
                    provider,
                    str(state),
                    now.isoformat(timespec="seconds"),
                    cooldown.isoformat(timespec="seconds") if cooldown else None,
                    detail,
                ),
            )

    def all(self) -> list[HealthRecord]:
        rows = self.conn.execute("SELECT * FROM provider_health ORDER BY provider")
        return [self._record(r) for r in rows]

    @staticmethod
    def _record(row: sqlite3.Row) -> HealthRecord:
        return HealthRecord(
            provider=row["provider"],
            state=ProviderState(row["state"]),
            checked_at=_parse(row["checked_at"]),
            cooldown_until=_parse(row["cooldown_until"]),
            detail=row["detail"],
        )
