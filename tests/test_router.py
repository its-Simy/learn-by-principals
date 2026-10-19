"""BL-035: Router v1 — config order, health states, cooldowns, benchmarks."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from core.ledger.ledger import Ledger
from core.memory.db import connect
from core.providers.models.base import (
    ModelRateLimited,
    ProviderState,
    TaskPackage,
    UsageHint,
)
from core.router.benchmarks import Benchmark, Benchmarks
from core.router.health import DEFAULT_COOLDOWN, cooldown_until
from core.router.router import MIN_SAMPLES, NoProvider, Router
from tests.fakes.fake_models import FakeModel

T0 = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


class Checked(FakeModel):
    """Counts health() calls."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.health_checks = 0

    def health(self):
        self.health_checks += 1
        return self.state


class Housekeeper(FakeModel):
    """A provider that takes only housekeeping task types (the router's ``task_types`` rule)."""

    task_types = frozenset({"classify", "extract_metadata", "summarize"})


@pytest.fixture
def conn():
    return connect(":memory:")


@pytest.fixture
def models():
    return {"claude": Checked("claude", "C"), "codex": Checked("codex", "X")}


def task(task_type="explain", output_format="text"):
    return TaskPackage(task_type, None, "", "q", 10, {}, output_format=output_format)


def seed(conn, provider, task_type, n, **metrics):
    marks = Benchmarks(conn)
    for _ in range(n):
        marks.record(provider, task_type, format_compliance=metrics.get("format_compliance", 1.0))
    extra = {k: v for k, v in metrics.items() if k != "format_compliance"}
    if extra:
        marks.record(provider, task_type, **extra)


# -- ordering ---------------------------------------------------------------------------------


def test_config_order_below_ten_samples(conn, models):
    seed(conn, "claude", "explain", MIN_SAMPLES - 1, accuracy=0.1)
    seed(conn, "codex", "explain", MIN_SAMPLES + 5, accuracy=0.99)
    router = Router(models, Ledger(conn), ["claude", "codex"])
    assert router.candidates("explain") == ["claude", "codex"]
    assert router.route("explain") is models["claude"]


def test_benchmark_order_at_ten_samples_or_more(conn, models):
    seed(conn, "claude", "explain", MIN_SAMPLES, accuracy=0.5, groundedness=0.5)
    seed(conn, "codex", "explain", MIN_SAMPLES, accuracy=0.9, groundedness=0.9)
    router = Router(models, Ledger(conn), ["claude", "codex"])

    assert router.candidates("explain") == ["codex", "claude"]
    assert router.run(task()).provider == "codex"
    # other task types keep config order
    assert router.candidates("critique") == ["claude", "codex"]


def test_composite_score_weights():
    b = Benchmark("x", "explain", 1.0, 0.0, 0.5, 100, None, 10)
    assert b.score == pytest.approx(0.4 * 1.0 + 0.3 * 0.0 + 0.3 * 0.5)
    only_format = Benchmark("x", "explain", None, None, 0.8, 100, 4.0, 10)
    assert only_format.score == pytest.approx(0.8)  # missing metrics are re-weighted away


def test_routing_is_per_task_type_then_purpose(conn, models):
    routing = {
        "teaching": ["claude", "codex"],
        "analysis": ["codex", "claude"],
        "critique": ["claude"],
    }
    router = Router(models, Ledger(conn), routing)
    assert router.order_for("explain") == ["claude", "codex"]
    assert router.order_for("grade") == ["codex", "claude"]
    assert router.order_for("critique") == ["claude"]
    assert router.order_for("something_new") == ["claude", "codex"]  # defaults to teaching


# -- health and cooldowns ---------------------------------------------------------------------


def test_rate_limited_provider_is_skipped_then_restored_after_cooldown(conn, models):
    clock = Clock()
    router = Router(models, Ledger(conn), ["claude", "codex"], clock=clock)
    models["claude"].limited = True

    assert router.run(task()).provider == "codex"  # claude hit its limit; fell back
    record = router.health.get("claude")
    assert record.state is ProviderState.RATE_LIMITED
    assert record.cooldown_until == T0 + DEFAULT_COOLDOWN

    clock.now = T0 + DEFAULT_COOLDOWN - timedelta(minutes=1)
    assert router.route("explain") is models["codex"]
    assert models["claude"].health_checks == 0  # no quota spent while cooling down

    # the limit has reset on the provider's side
    models["claude"].limited = False
    models["claude"].state = ProviderState.AVAILABLE
    clock.now = T0 + DEFAULT_COOLDOWN + timedelta(minutes=1)
    assert router.route("explain") is models["claude"]
    assert models["claude"].health_checks == 1
    assert router.health.get("claude").cooldown_until is None
    assert router.run(task()).provider == "claude"


def test_still_limited_after_cooldown_starts_a_new_one(conn, models):
    clock = Clock()
    router = Router(models, Ledger(conn), ["claude", "codex"], clock=clock)
    models["claude"].limited = True
    router.run(task())

    clock.now = T0 + DEFAULT_COOLDOWN + timedelta(minutes=1)
    assert router.route("explain") is models["codex"]
    assert router.health.get("claude").cooldown_until == clock.now + DEFAULT_COOLDOWN


def test_cooldown_holds_across_commands(conn, models):
    clock = Clock()
    models["claude"].limited = True
    Router(models, Ledger(conn), ["claude", "codex"], clock=clock).run(task())

    fresh = {"claude": Checked("claude", "C"), "codex": Checked("codex", "X")}  # a new process
    later = Router(fresh, Ledger(conn), ["claude", "codex"], clock=Clock(T0 + timedelta(minutes=5)))
    assert later.route("explain") is fresh["codex"]
    assert fresh["claude"].health_checks == 0


def test_cooldown_comes_from_the_usage_hint(conn, models):
    clock = Clock()
    router = Router(models, Ledger(conn), ["claude", "codex"], clock=clock)
    resets = (T0 + timedelta(minutes=10)).isoformat()

    def limited(t):
        raise ModelRateLimited("limit", UsageHint(resets_at=resets))

    models["claude"].run = limited
    router.run(task())
    assert router.health.get("claude").cooldown_until == T0 + timedelta(minutes=10)


@pytest.mark.parametrize(
    "resets_at, expected",
    [
        ((T0 + timedelta(hours=2)).isoformat(), T0 + timedelta(hours=2)),
        (str(int((T0 + timedelta(minutes=30)).timestamp())), T0 + timedelta(minutes=30)),
        ("in 45 minutes", T0 + timedelta(minutes=45)),
        ("3pm", T0 + DEFAULT_COOLDOWN),  # unreadable: the default
        ((T0 - timedelta(hours=1)).isoformat(), T0 + DEFAULT_COOLDOWN),  # already past
        (None, T0 + DEFAULT_COOLDOWN),
    ],
)
def test_cooldown_until(resets_at, expected):
    assert cooldown_until(UsageHint(resets_at=resets_at), T0) == expected


@pytest.mark.parametrize(
    "state", [ProviderState.AUTH_EXPIRED, ProviderState.BROKEN, ProviderState.DISABLED]
)
def test_unusable_states_are_dropped(conn, models, state):
    models["claude"].state = state
    router = Router(models, Ledger(conn), ["claude", "codex"])
    assert router.candidates("explain") == ["codex"]
    run = router.run(task())
    assert run.provider == "codex"
    (row,) = conn.execute("SELECT provider, fallback_from FROM model_runs")
    assert tuple(row) == ("codex", "claude")


def test_limited_is_still_usable(conn, models):
    models["claude"].state = ProviderState.LIMITED
    assert Router(models, Ledger(conn), ["claude", "codex"]).candidates("explain")[0] == "claude"


def test_no_allowed_available_provider_raises_no_provider(conn):
    models = {"claude": Checked("claude"), "local": Housekeeper("local")}
    models["claude"].state = ProviderState.RATE_LIMITED
    router = Router(models, Ledger(conn), ["claude", "local", "codex"], clock=Clock())

    with pytest.raises(NoProvider) as info:
        router.route("explain")
    message = str(info.value)
    assert message.startswith("No model provider left for explain:")
    assert "claude is RATE_LIMITED until 2026-09-23T13:00" in message
    assert "local doesn't take explain" in message
    assert "codex is not configured" in message
    assert router.route("classify") is models["local"]


def test_no_model_installed_at_all_says_what_to_install(conn, models):
    """A fresh NotebookLM-only setup: every CLI is DISABLED, so the 502 names the optional step."""
    from core.router.router import INSTALL_MODELS_HINT

    for model in models.values():
        model.state = ProviderState.DISABLED
    with pytest.raises(NoProvider) as info:
        Router(models, Ledger(conn), ["claude", "codex"]).route("explain")
    assert str(info.value).endswith(INSTALL_MODELS_HINT)
    # A rate limit is not "nothing installed": no install hint then.
    models["claude"].state = ProviderState.RATE_LIMITED
    with pytest.raises(NoProvider) as info:
        Router(models, Ledger(conn), ["claude", "codex"], clock=Clock()).route("explain")
    assert INSTALL_MODELS_HINT not in str(info.value)


def test_excluded_providers_are_named_in_the_message(conn, models):
    with pytest.raises(NoProvider, match="claude is excluded for this task"):
        Router(models, Ledger(conn), ["claude"]).run(task(), exclude={"claude"})


# -- automatic measurements -------------------------------------------------------------------


def test_every_run_records_format_compliance_and_latency(conn):
    models = {"claude": FakeModel("claude", replies=["not json", json.dumps([{"a": 1}]), "prose"])}
    router = Router(models, Ledger(conn))
    router.run(task("analyze_transcript", "json"))
    router.run(task("analyze_transcript", "json"))
    router.run(task("explain"))

    marks = Benchmarks(conn)
    analyzed = marks.for_task("analyze_transcript")["claude"]
    assert (analyzed.format_compliance, analyzed.sample_count) == (0.5, 2)
    assert analyzed.latency_ms == 5
    assert marks.for_task("explain")["claude"].format_compliance == 1.0


def test_samples_are_append_only(conn):
    import sqlite3

    Benchmarks(conn).record("claude", "explain", accuracy=1.0)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM benchmark_samples")


def test_rate_validates_and_records(conn, models):
    router = Router(models, Ledger(conn))
    router.rate("claude", "explain", 4)
    with pytest.raises(ValueError):
        router.rate("claude", "explain", 6)
    assert Benchmarks(conn).for_task("explain")["claude"].learner_rating == 4


# -- BL-040: one fallback per task -----------------------------------------------------------


def test_one_fallback_per_task(conn):
    from core.providers.models.base import ModelError

    models = {n: Checked(n) for n in ("claude", "codex", "third")}

    def boom(task):
        raise ModelError("crashed")

    models["claude"].run = boom
    models["codex"].run = boom
    router = Router(models, Ledger(conn), ["claude", "codex", "third"])

    with pytest.raises(ModelError, match="crashed"):
        router.run(task())
    assert models["third"].tasks == []  # a second fallback is never tried
    rows = conn.execute("SELECT provider, fallback_from FROM model_runs ORDER BY rowid").fetchall()
    assert [tuple(r) for r in rows] == [("claude", None), ("codex", "claude")]


def test_a_skipped_preferred_provider_is_the_one_fallback(conn):
    from core.providers.models.base import ModelError

    models = {n: Checked(n) for n in ("claude", "codex", "third")}
    models["claude"].state = ProviderState.DISABLED

    def boom(task):
        raise ModelError("crashed")

    models["codex"].run = boom
    with pytest.raises(ModelError):
        Router(models, Ledger(conn), ["claude", "codex", "third"]).run(task())
    assert models["third"].tasks == []


def test_the_error_raised_names_the_provider_that_raised_it(conn, models):
    """So the API can say which provider failed (BL-044's 502 body)."""
    models["claude"].limited = True
    models["codex"].limited = True
    with pytest.raises(ModelRateLimited) as caught:
        Router(models, Ledger(conn), ["claude", "codex"]).run(task())
    assert caught.value.provider == "codex"  # the last one tried
