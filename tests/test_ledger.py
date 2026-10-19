from datetime import UTC, datetime

from core.ledger.ledger import Ledger, ModelRun
from core.memory.db import connect
from core.providers.models.base import ModelRateLimited, TaskPackage
from tests.fakes.fake_models import FakeModel


def task() -> TaskPackage:
    return TaskPackage("explain", "simplifier", "You are a tutor.", "What is a pointer?", 256)


def test_one_run_is_one_row_with_the_right_fields():
    conn = connect(":memory:")
    ledger = Ledger(conn)
    result = FakeModel("claude", reply="An address.").run(task())

    ledger.record(ModelRun.from_result(task(), result, "2026-09-23T12:00:00+00:00"))

    (row,) = [dict(r) for r in conn.execute("SELECT * FROM model_runs")]
    assert row["provider"] == "claude"
    assert row["model"] == "claude-model"
    assert row["task_type"] == "explain"
    assert row["persona"] == "simplifier"
    assert row["started_at"] == "2026-09-23T12:00:00+00:00"
    assert row["duration_ms"] == 5
    assert row["success"] == 1
    assert (row["input_tokens_est"], row["output_tokens_est"]) == (10, 2)  # from the usage hint
    assert row["fallback_from"] is None and row["error"] is None
    assert len(row["run_id"]) == 32


def test_failed_run_is_recorded_with_its_error():
    conn = connect(":memory:")
    model = FakeModel("claude")
    model.state = model.state.RATE_LIMITED
    try:
        model.run(task())
    except ModelRateLimited as exc:
        Ledger(conn).record(
            ModelRun.from_error(task(), "claude", exc, "2026-09-23T12:00:00+00:00", 40, "codex")
        )
    row = dict(conn.execute("SELECT * FROM model_runs").fetchone())
    assert row["success"] == 0
    assert row["error"] == "ModelRateLimited: claude usage limit reached"
    assert row["fallback_from"] == "codex"
    assert row["input_tokens_est"] > 0


def test_today_summary_groups_todays_runs_by_provider():
    conn = connect(":memory:")
    ledger = Ledger(conn)
    for provider, started, success in [
        ("claude", "2026-09-23T09:00:00+00:00", True),
        ("claude", "2026-09-23T10:00:00+00:00", False),
        ("codex", "2026-09-23T11:00:00+00:00", True),
        ("claude", "2026-09-22T23:00:00+00:00", True),  # yesterday
    ]:
        ledger.record(
            ModelRun(provider, "explain", started, success, duration_ms=100, input_tokens_est=10)
        )

    summary = ledger.today_summary(datetime(2026, 9, 23, 15, tzinfo=UTC))

    assert [
        (s.provider, s.runs, s.failures, s.duration_ms, s.input_tokens_est) for s in summary
    ] == [
        ("claude", 2, 1, 200, 20),
        ("codex", 1, 0, 100, 10),
    ]
