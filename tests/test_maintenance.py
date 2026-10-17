"""BL-038: retention decay, session archiving, and the once-a-day automatic run."""

from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from cli.app import app
from core.config import load_config
from core.maintenance import due, last_run, maintain, maybe_maintain
from core.memory.db import connect
from core.memory.learner import Concept, LearnerMemory
from core.memory.vault import Vault

T0 = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
HALF_LIFE = 21


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> str:
        return iso(self.now)


@pytest.fixture
def world(tmp_path):
    conn = connect(":memory:")
    clock = Clock(T0 - timedelta(days=HALF_LIFE))
    learner = LearnerMemory(conn, now=clock)
    for cid in ("cse220/stale", "cse220/fresh"):
        learner.upsert_concept(Concept(cid, "CSE220", cid))
    e = learner.add_evidence("cse220/stale", "applied", "strong")
    learner.set_mastery("cse220/stale", 3, 0.8, [e])
    e = learner.add_evidence("cse220/fresh", "applied", "strong")
    learner.set_mastery("cse220/fresh", 3, 0.8, [e])
    return conn, learner, clock, tmp_path / "vault"


def retention(learner, cid):
    return learner.get_mastery(cid).retention_confidence


def test_decay_halves_retention_at_exactly_one_half_life(world):
    conn, learner, _, vault = world
    report = maintain(conn, vault, T0, HALF_LIFE)
    assert retention(learner, "cse220/stale") == pytest.approx(0.4)
    assert learner.get_mastery("cse220/stale").level == 3  # the level itself never decays
    assert {c.concept_id for c in report.decayed} == {"cse220/stale", "cse220/fresh"}
    assert maintain(conn, vault, T0, HALF_LIFE).decayed == []  # idempotent for the same moment


def test_two_half_lives_quarter_it(world):
    conn, learner, _, vault = world
    maintain(conn, vault, T0 + timedelta(days=HALF_LIFE), HALF_LIFE)
    assert retention(learner, "cse220/stale") == pytest.approx(0.2)


def test_a_concept_with_fresh_evidence_is_untouched(world):
    conn, learner, clock, vault = world
    maintain(conn, vault, T0, HALF_LIFE)  # the previous run
    fresh_before = retention(learner, "cse220/fresh")
    clock.now = T0 + timedelta(hours=2)
    learner.add_evidence("cse220/fresh", "explained", "moderate")  # evidence since that run

    report = maintain(conn, vault, T0 + timedelta(days=7), HALF_LIFE)

    assert retention(learner, "cse220/fresh") == fresh_before
    assert [c.concept_id for c in report.decayed] == ["cse220/stale"]
    assert retention(learner, "cse220/stale") == pytest.approx(0.8 * 0.5 ** (28 / 21))


def test_half_life_comes_from_config(monkeypatch):
    monkeypatch.setenv("BRIGHTLEARN_RETENTION_HALF_LIFE_DAYS", "10")
    assert load_config().retention_half_life_days == 10
    monkeypatch.delenv("BRIGHTLEARN_RETENTION_HALF_LIFE_DAYS")
    assert load_config().retention_half_life_days == 21


def test_old_ended_sessions_are_archived_not_deleted(world):
    conn, learner, clock, vault_root = world
    vault = Vault(vault_root)
    rows = {}
    for name, age, ended in [("old", 31, True), ("recent", 29, True), ("stuck", 60, False)]:
        clock.now = T0 - timedelta(days=age)
        row = learner.start_session("CSE220")
        vault.session_transcript_path(row.session_id).parent.mkdir(parents=True, exist_ok=True)
        vault.session_transcript_path(row.session_id).write_text(f"# {name}")
        if ended:
            row.ended_at = iso(clock.now + timedelta(hours=1))
            row.summary_path = str(vault.write_session_summary(row, name))
            learner.update_session(row)
        rows[name] = row

    report = maintain(conn, vault_root, T0, HALF_LIFE)

    archive = vault_root / "sessions" / "archive"
    old, stuck = rows["old"].session_id, rows["stuck"].session_id
    assert report.closed == [stuck]  # idle for 60 days: closed (BL-040), then old enough to archive
    assert report.archived == [old, stuck]
    assert (archive / f"{old}.md").read_text() == "# old"
    assert (archive / f"{old}.summary.md").exists()
    assert not vault.session_transcript_path(old).exists()
    assert learner.get_session(old).summary_path == str(archive / f"{old}.summary.md")
    assert vault.session_transcript_path(rows["recent"].session_id).exists()
    assert learner.get_session(stuck).ended_at == iso(T0)
    assert maintain(conn, vault_root, T0 + timedelta(days=1), HALF_LIFE).archived == []


def test_auto_run_guard_respects_the_24_hour_window(world):
    conn, _, _, vault = world
    assert due(conn, T0) and last_run(conn) is None
    assert maybe_maintain(conn, vault, HALF_LIFE, now=lambda: T0) is not None
    assert last_run(conn) == T0
    assert maybe_maintain(conn, vault, HALF_LIFE, now=lambda: T0 + timedelta(hours=23)) is None
    assert not due(conn, T0 + timedelta(hours=23, minutes=59))
    assert maybe_maintain(conn, vault, HALF_LIFE, now=lambda: T0 + timedelta(hours=24)) is not None
    triggers = [r[0] for r in conn.execute("SELECT trigger FROM maintenance_runs ORDER BY id")]
    assert triggers == ["auto", "auto"]


def _runs():
    conn = connect(load_config().db_path)
    return [tuple(r) for r in conn.execute("SELECT trigger, decayed FROM maintenance_runs")]


def test_other_commands_run_it_first_once_a_day(monkeypatch):
    from core import doctor

    monkeypatch.setattr(doctor, "checks", lambda config: [])  # no real provider checks
    conn = connect(load_config().db_path)  # a database with something to maintain
    learner = LearnerMemory(conn, now=lambda: iso(datetime.now(UTC) - timedelta(days=30)))
    learner.upsert_concept(Concept("cse220/x", "CSE220", "X"))
    learner.set_mastery("cse220/x", 2, 0.6, [learner.add_evidence("cse220/x", "applied", "weak")])
    conn.close()

    assert CliRunner().invoke(app, ["sessions", "list"]).exit_code == 0
    assert _runs() == [("auto", 1)]
    assert CliRunner().invoke(app, ["sessions", "list"]).exit_code == 0
    assert _runs() == [("auto", 1)]  # within 24 hours: not again
    assert CliRunner().invoke(app, ["doctor"]).exit_code == 0
    assert _runs() == [("auto", 1)]  # doctor stays read-only


def test_no_database_means_no_auto_run():
    assert CliRunner().invoke(app, ["sessions", "list"]).exit_code == 0
    assert load_config().db_path.exists()  # created by `sessions list`, not by maintenance
    assert _runs() == []


def test_maintain_command_prints_what_changed():
    conn = connect(load_config().db_path)
    learner = LearnerMemory(conn, now=lambda: iso(datetime.now(UTC) - timedelta(days=21)))
    learner.upsert_concept(Concept("cse220/x", "CSE220", "X"))
    learner.set_mastery("cse220/x", 2, 0.8, [learner.add_evidence("cse220/x", "applied", "weak")])
    conn.close()

    result = CliRunner().invoke(app, ["maintain"])

    assert result.exit_code == 0, result.output
    assert "cse220/x" in result.output and "0.80 → 0.40" in result.output
    assert "nothing old enough to archive" in result.output
    assert _runs() == [("manual", 1)]


# -- BL-040: idle sessions ---------------------------------------------------------------------


def test_maintain_closes_sessions_idle_over_24_hours(world):
    conn, learner, clock, vault = world
    clock.now = T0 - timedelta(hours=30)
    idle = learner.start_session("CSE220")
    clock.now = T0 - timedelta(hours=26)
    busy = learner.start_session("CSE214")
    clock.now = T0 - timedelta(hours=1)
    learner.touch_session(busy)  # a turn an hour ago

    report = maintain(conn, vault, T0, HALF_LIFE)

    assert report.closed == [idle.session_id]
    assert learner.get_session(idle.session_id).ended_at == iso(T0)
    assert learner.get_session(busy.session_id).ended_at is None
    assert conn.execute("SELECT closed FROM maintenance_runs").fetchone()[0] == 1
