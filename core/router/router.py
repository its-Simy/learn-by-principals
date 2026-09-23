"""Model Router v1: the only code that runs a model. Every attempt goes to the ledger.

``route(task_type)`` picks a provider:

1. the ``[routing]`` order for the task type (its own key, else its purpose's, see
   ``TASK_PURPOSE``), minus providers that don't take that task type;
2. minus providers that are RATE_LIMITED, AUTH_EXPIRED, BROKEN or DISABLED;
3. ordered by the benchmarks' composite score when every candidate has at least
   ``MIN_SAMPLES`` measured runs of that task, else in config order.

``run`` tries the candidates in that order and falls back to the next on any model error.
A rate limit puts the provider in a cooldown (from its usage hint, default 60 minutes) that is
kept in ``provider_health``, so it holds across commands; once it has passed, the provider
comes back after a successful ``health()`` check. Other failures only last for this process.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime

from core.jsonutil import extract_json_array
from core.ledger.ledger import Ledger, ModelRun, utcnow
from core.providers.models.base import (
    ModelError,
    ModelProvider,
    ModelRateLimited,
    ModelResult,
    ProviderState,
    TaskPackage,
    UsageHint,
)
from core.router.benchmarks import Benchmarks
from core.router.health import HealthStore, cooldown_until

log = logging.getLogger(__name__)

MIN_SAMPLES = 10
UNUSABLE = frozenset(
    {
        ProviderState.RATE_LIMITED,
        ProviderState.AUTH_EXPIRED,
        ProviderState.BROKEN,
        ProviderState.DISABLED,
    }
)

# The `[routing]` purpose a task type falls back to when config has no key for it.
TASK_PURPOSE = {
    "explain": "teaching",
    "analogy": "teaching",
    "exemplify": "teaching",
    "question_gen": "teaching",
    "tutor_estimate": "teaching",
    "analyze_transcript": "analysis",
    "critique": "analysis",
    "grade": "analysis",
    "classify": "housekeeping",
    "extract_metadata": "housekeeping",
    "summarize": "housekeeping",
}

Routing = Sequence[str] | Mapping[str, Sequence[str]]


class NoProvider(ModelError):
    """No provider may take this task right now; the message says why for each one."""


def _now() -> datetime:
    return datetime.now(UTC)


def format_compliance(task: TaskPackage, text: str) -> float:
    """1.0 when the output is in the shape the task asked for (a JSON array for "json")."""
    if task.output_format == "json":
        return 1.0 if extract_json_array(text) is not None else 0.0
    return 1.0 if text.strip() else 0.0


class Router:
    def __init__(
        self,
        providers: dict[str, ModelProvider],
        ledger: Ledger,
        order: Routing | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        """``order`` is one provider list for every task, or ``[routing]``-style
        ``{task type or purpose: [providers]}``; None means ``providers`` in their order."""
        self.providers = providers
        self._ledger = ledger
        self._routing = order
        self._clock = clock
        self.benchmarks = Benchmarks(ledger.conn)
        self.health = HealthStore(ledger.conn)
        self._failed: dict[str, ProviderState] = {}  # this process only
        self.last: tuple[str, str] | None = None  # (provider, task type) of the last success

    # -- choosing -----------------------------------------------------------------------------

    def order_for(self, task_type: str) -> list[str]:
        routing = self._routing
        if routing is None:
            return list(self.providers)
        if not isinstance(routing, Mapping):
            return list(routing)
        purpose = TASK_PURPOSE.get(task_type, "teaching")
        return list(routing.get(task_type) or routing.get(purpose) or self.providers)

    def allows(self, name: str, task_type: str) -> bool:
        """Providers may limit themselves with a ``task_types`` attribute (e.g. Ollama)."""
        allowed = getattr(self.providers[name], "task_types", None)
        return allowed is None or task_type in allowed

    def state(self, name: str) -> ProviderState:
        provider = self.providers[name]
        now = self._clock()
        record = self.health.get(name)
        if record is not None and record.cooldown_until is not None:
            if now < record.cooldown_until:
                return ProviderState.RATE_LIMITED
            state = provider.health()  # the cooldown is over: check before trusting it again
            if state is ProviderState.RATE_LIMITED:
                self._rate_limited(name, provider.usage_hint())
            else:
                self.health.set(name, state, now)
                self._failed.pop(name, None)
            return state
        if name in self._failed:
            return self._failed[name]
        state = getattr(provider, "state", None)
        if state is None:
            state = provider.health()
            self.health.set(name, state, now)
        if state is ProviderState.RATE_LIMITED:
            self._rate_limited(name, provider.usage_hint())
        return state

    def candidates(
        self, task_type: str, exclude: frozenset[str] | set[str] = frozenset()
    ) -> list[str]:
        usable: list[str] = []
        why: list[str] = []
        for name in self.order_for(task_type):
            if name not in self.providers:
                why.append(f"{name} is not configured")
            elif name in exclude:
                why.append(f"{name} is excluded for this task")
            elif not self.allows(name, task_type):
                why.append(f"{name} doesn't take {task_type}")
            elif (state := self.state(name)) in UNUSABLE:
                why.append(f"{name} is {state}{self._until(name)}")
            else:
                usable.append(name)
        if not usable:
            raise NoProvider(
                f"No model provider left for {task_type}: " + ("; ".join(why) or "none configured")
            )
        return self._rank(task_type, usable)

    def route(
        self, task_type: str, exclude: frozenset[str] | set[str] = frozenset()
    ) -> ModelProvider:
        return self.providers[self.candidates(task_type, exclude)[0]]

    def _rank(self, task_type: str, names: list[str]) -> list[str]:
        marks = self.benchmarks.for_task(task_type)
        measured = all(
            n in marks and marks[n].sample_count >= MIN_SAMPLES and marks[n].score is not None
            for n in names
        )
        if not measured:
            return names
        return sorted(names, key=lambda n: -marks[n].score)  # stable: ties keep config order

    # -- running ------------------------------------------------------------------------------

    def run(
        self, task: TaskPackage, exclude: frozenset[str] | set[str] = frozenset()
    ) -> ModelResult:
        """Run on the best usable provider, falling back on errors. ``exclude`` keeps named
        providers out (principle 6)."""
        last_error: ModelError | None = None
        names = self.candidates(task.task_type, exclude)
        # The ledger notes a fallback when the preferred provider was skipped as unusable.
        preferred = next(
            (
                n
                for n in self.order_for(task.task_type)
                if n in self.providers and n not in exclude and self.allows(n, task.task_type)
            ),
            None,
        )
        fallback_from = preferred if preferred not in names else None
        for name in names:
            provider = self.providers[name]
            started, t0 = utcnow(), time.monotonic()
            try:
                result = provider.run(task)
            except ModelRateLimited as exc:
                self._ledger.record(
                    ModelRun.from_error(task, name, exc, started, _ms(t0), fallback_from)
                )
                self._rate_limited(name, exc.hint or provider.usage_hint())
                last_error, fallback_from = exc, fallback_from or name
                continue
            except ModelError as exc:
                self._ledger.record(
                    ModelRun.from_error(task, name, exc, started, _ms(t0), fallback_from)
                )
                self._fail(name, provider, exc)
                last_error, fallback_from = exc, fallback_from or name
                continue
            self._ledger.record(ModelRun.from_result(task, result, started, fallback_from))
            self.benchmarks.record(
                result.provider,
                task.task_type,
                format_compliance=format_compliance(task, result.text),
                latency_ms=result.duration_ms,
            )
            self.last = (result.provider, task.task_type)
            return result
        assert last_error is not None
        raise last_error

    def rate(self, provider: str, task_type: str, rating: int) -> None:
        """``/rate 1-5`` from the learner, for the provider that answered."""
        if not 1 <= rating <= 5:
            raise ValueError("A rating is 1 to 5")
        self.benchmarks.record(provider, task_type, learner_rating=rating)

    # -- state changes ------------------------------------------------------------------------

    def _rate_limited(self, name: str, hint: UsageHint | None) -> None:
        now = self._clock()
        until = cooldown_until(hint, now)
        detail = hint.limit_message if hint else None
        self.health.set(name, ProviderState.RATE_LIMITED, now, until, detail)
        log.info("%s is rate limited until %s", name, until.isoformat(timespec="minutes"))

    def _fail(self, name: str, provider: ModelProvider, exc: ModelError) -> None:
        state = getattr(provider, "state", None)
        if state not in UNUSABLE:
            state = ProviderState.BROKEN
        self._failed[name] = state
        self.health.set(name, state, self._clock(), detail=str(exc)[:300])
        log.warning("%s failed (%s); falling back: %s", name, state, exc)

    def _until(self, name: str) -> str:
        record = self.health.get(name)
        if record and record.cooldown_until and self._clock() < record.cooldown_until:
            return f" until {record.cooldown_until.isoformat(timespec='minutes')}"
        return ""


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)
