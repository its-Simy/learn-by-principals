"""Model Router v0: the only code that runs a model. Every attempt goes to the ledger.

v0 routing is fixed, per TICKETS-2 BL-026: try providers in ``order`` (Claude, then Codex) and
move on only when the current one is rate limited. The benchmarks-driven router (principle 8)
replaces this in Phase 10.
"""

from __future__ import annotations

import logging
import time

from core.ledger.ledger import Ledger, ModelRun, utcnow
from core.providers.models.base import (
    ModelError,
    ModelProvider,
    ModelRateLimited,
    ModelResult,
    ProviderState,
    TaskPackage,
)

log = logging.getLogger(__name__)


class Router:
    def __init__(
        self, providers: dict[str, ModelProvider], ledger: Ledger, order: list[str] | None = None
    ) -> None:
        self.providers = providers
        self._ledger = ledger
        self.order = order or list(providers)

    def run(
        self, task: TaskPackage, exclude: set[str] | frozenset[str] = frozenset()
    ) -> ModelResult:
        """Run on the first usable provider; ``exclude`` keeps named providers out (principle 6)."""
        candidates = [n for n in self.order if n in self.providers and n not in exclude]
        if not candidates:
            raise ModelError(f"No model provider left for {task.task_type} (excluded {exclude})")
        last_error: ModelError | None = None
        fallback_from: str | None = None
        for name in candidates:
            provider = self.providers[name]
            if (
                getattr(provider, "state", None) is ProviderState.RATE_LIMITED
                and name != candidates[-1]
            ):
                log.info("%s is rate limited; skipping to the next provider", name)
                fallback_from = fallback_from or name
                continue
            started, t0 = utcnow(), time.monotonic()
            try:
                result = provider.run(task)
            except ModelRateLimited as exc:
                self._ledger.record(
                    ModelRun.from_error(task, name, exc, started, _ms(t0), fallback_from)
                )
                last_error, fallback_from = exc, fallback_from or name
                continue
            except ModelError as exc:
                self._ledger.record(
                    ModelRun.from_error(task, name, exc, started, _ms(t0), fallback_from)
                )
                raise
            self._ledger.record(ModelRun.from_result(task, result, started, fallback_from))
            return result
        assert last_error is not None
        raise last_error


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)
