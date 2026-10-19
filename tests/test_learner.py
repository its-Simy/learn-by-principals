import sqlite3

import pytest

from core.memory.db import connect
from core.memory.learner import (
    Concept,
    LearnerError,
    LearnerMemory,
    MasteryWithoutEvidence,
    retention,
)


class Now:
    def __init__(self, value="2026-09-23T12:00:00+00:00"):
        self.value = value

    def __call__(self):
        return self.value


@pytest.fixture
def now():
    return Now()


@pytest.fixture
def mem(now):
    mem = LearnerMemory(connect(":memory:"), now=now)
    for cid, name, tags in [
        ("cse220/pointers", "Pointers", ["midterm-1"]),
        ("cse220/bit-ops", "Bitwise operations", ["midterm-1"]),
        ("cse220/structs", "Structs", ["final"]),
        ("cse220/unseen", "Unions", ["midterm-1"]),
    ]:
        mem.upsert_concept(Concept(cid, "CSE220", name, "Week 3", [], tags))
    return mem


def test_upsert_concept_round_trips_lists(mem):
    mem.upsert_concept(
        Concept("cse220/pointers", "CSE220", "Pointers", "Week 4", ["cse220/bit-ops"], ["final"])
    )
    got = mem.get_concept("cse220/pointers")
    assert got.module == "Week 4"
    assert got.prerequisites == ["cse220/bit-ops"]
    assert got.exam_tags == ["final"]
    assert len(mem.concepts("CSE220")) == 4


def test_set_mastery_without_evidence_raises(mem):
    with pytest.raises(MasteryWithoutEvidence):
        mem.set_mastery("cse220/pointers", 2, 0.7, [])
    assert mem.get_mastery("cse220/pointers") is None


def test_set_mastery_refuses_evidence_for_another_concept(mem):
    other = mem.add_evidence("cse220/structs", "explained", "strong")
    with pytest.raises(MasteryWithoutEvidence):
        mem.set_mastery("cse220/pointers", 2, 0.7, [other])
    with pytest.raises(MasteryWithoutEvidence):
        mem.set_mastery("cse220/pointers", 2, 0.7, ["no-such-id"])


def test_set_mastery_records_evidence_summary(mem, now):
    first = mem.add_evidence("cse220/pointers", "explained", "moderate", session_id="s1")
    now.value = "2026-09-24T09:00:00+00:00"
    second = mem.add_evidence("cse220/pointers", "applied", "strong", session_id="s2")

    mastery = mem.set_mastery("cse220/pointers", 3, 0.8, [first, second])

    assert mastery == mem.get_mastery("cse220/pointers")
    assert (mastery.level, mastery.evidence_count) == (3, 2)
    assert mastery.last_evidence_at == "2026-09-24T09:00:00+00:00"
    assert mastery.retention_confidence == 0.8


def test_set_mastery_validates_ranges(mem):
    e = mem.add_evidence("cse220/pointers", "applied", "strong")
    with pytest.raises(LearnerError):
        mem.set_mastery("cse220/pointers", 6, 0.5, [e])
    with pytest.raises(LearnerError):
        mem.set_mastery("cse220/pointers", 3, 1.5, [e])


def test_add_evidence_validates_type_strength_and_concept(mem):
    with pytest.raises(LearnerError):
        mem.add_evidence("cse220/pointers", "guessed", "strong")
    with pytest.raises(LearnerError):
        mem.add_evidence("cse220/pointers", "applied", "huge")
    with pytest.raises(LearnerError):
        mem.add_evidence("cse220/nope", "applied", "strong")


def test_evidence_is_append_only(mem):
    e = mem.add_evidence("cse220/pointers", "applied", "strong")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        mem.conn.execute("UPDATE evidence SET strength = 'weak' WHERE evidence_id = ?", (e,))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        mem.conn.execute("DELETE FROM evidence WHERE evidence_id = ?", (e,))


def set_level(mem, cid, level, confidence):
    e = mem.add_evidence(cid, "applied", "moderate")
    mem.set_mastery(cid, level, confidence, [e])


def test_weakest_orders_by_level_then_retention_then_confidence(mem):
    set_level(mem, "cse220/pointers", 3, 0.9)
    set_level(mem, "cse220/bit-ops", 1, 0.9)
    set_level(mem, "cse220/structs", 1, 0.4)

    order = [c.concept_id for c, _ in mem.weakest("CSE220", 10)]

    assert order == ["cse220/unseen", "cse220/structs", "cse220/bit-ops", "cse220/pointers"]
    unseen = mem.weakest("CSE220", 1)[0][1]
    assert (unseen.level, unseen.evidence_count) == (0, 0)


def test_weakest_limits_and_filters_by_exam_tag(mem):
    set_level(mem, "cse220/pointers", 3, 0.9)
    set_level(mem, "cse220/bit-ops", 1, 0.9)
    set_level(mem, "cse220/structs", 0, 0.1)

    assert [c.concept_id for c, _ in mem.weakest("CSE220", 2, exam_tag="midterm-1")] == [
        "cse220/unseen",
        "cse220/bit-ops",
    ]


def test_decay_lowers_stale_rows_and_leaves_fresh_ones(mem, now):
    now.value = "2026-09-01T12:00:00+00:00"
    set_level(mem, "cse220/structs", 3, 0.8)  # 22 days before the check
    now.value = "2026-09-23T00:00:00+00:00"
    set_level(mem, "cse220/pointers", 3, 0.8)  # 12 hours before the check

    changed = mem.decay_retention("2026-09-23T12:00:00+00:00")

    assert [c.concept_id for c in changed] == ["cse220/structs", "cse220/pointers"]
    stale = mem.get_mastery("cse220/structs")
    assert stale.retention_confidence == pytest.approx(retention(0.8, 22))
    assert stale.retention_confidence < 0.8
    assert stale.level == 3  # the level itself never decays
    # 12 hours: barely decayed at a 21-day half-life
    assert mem.get_mastery("cse220/pointers").retention_confidence == pytest.approx(
        retention(0.8, 0.5)
    )
    assert mem.decay_retention("2026-09-23T12:00:00+00:00") == []  # idempotent


def test_sessions_round_trip(mem, now):
    session = mem.start_session("CSE220", tutor_provider="claude")
    session.ended_at = "2026-09-23T13:00:00+00:00"
    session.analyzer_provider = "codex"
    session.summary_path = "memory/sessions/x.md"
    mem.update_session(session)
    assert mem.get_session(session.session_id) == session


def test_every_set_mastery_writes_a_history_row_with_its_evidence(mem, now):
    first = mem.add_evidence("cse220/pointers", "explained", "moderate")
    mem.set_mastery("cse220/pointers", 2, 0.6, [first])
    now.value = "2026-09-24T09:00:00+00:00"
    second = mem.add_evidence("cse220/pointers", "applied", "strong")
    mem.set_mastery("cse220/pointers", 3, 0.8, [first, second], changed_by="analyzer")

    one, two = mem.mastery_history("cse220/pointers")
    assert (one.old_level, one.new_level, one.evidence_ids, one.changed_by) == (
        None,
        2,
        [first],
        "manual",
    )
    assert (two.old_level, two.new_level, two.confidence) == (2, 3, 0.8)
    assert two.evidence_ids == [first, second]
    assert (two.changed_at, two.changed_by) == ("2026-09-24T09:00:00+00:00", "analyzer")


def test_refused_set_mastery_writes_no_history(mem):
    with pytest.raises(MasteryWithoutEvidence):
        mem.set_mastery("cse220/pointers", 2, 0.7, [])
    assert mem.mastery_history("cse220/pointers") == []


def test_mastery_history_is_append_only_and_changer_is_checked(mem):
    e = mem.add_evidence("cse220/pointers", "applied", "strong")
    with pytest.raises(LearnerError):
        mem.set_mastery("cse220/pointers", 3, 0.8, [e], changed_by="tutor")
    mem.set_mastery("cse220/pointers", 3, 0.8, [e])
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        mem.conn.execute("DELETE FROM mastery_history")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        mem.conn.execute("UPDATE mastery_history SET new_level = 5")
