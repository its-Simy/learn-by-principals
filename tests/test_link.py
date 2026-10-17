from dataclasses import replace

import pytest

from core.memory.db import Manifest, ResourceRow, connect
from core.providers.knowledge.base import KnowledgeRateLimited
from core.sync.link import LinkStep
from tests.fakes.fake_knowledge import FakeKnowledge


@pytest.fixture
def db() -> Manifest:
    return Manifest(connect(":memory:"))


@pytest.fixture
def kp() -> FakeKnowledge:
    return FakeKnowledge()


def add_row(db, tmp_path, n, bucket, state="synced", added_at="now", **kw) -> ResourceRow:
    path = tmp_path / f"{n}.pdf"
    path.write_text(f"file {n}")
    row = ResourceRow(
        resource_id=f"r{n}",
        course="CSE220",
        title=f"T{n}",
        added_at=added_at,
        url="https://zoom.example/rec" if state == "link" else None,
        local_path=None if state == "link" else str(path),
        bucket=None if state == "link" else bucket,
        hash=f"h{n}",
        sync_state=state,
        **kw,
    )
    db.upsert(row)
    return row


def adds(kp):
    return [c for c in kp.calls if c[0] == "add_file"]


def test_synced_rows_become_sources(db, kp, tmp_path):
    for i, bucket in enumerate(["syllabus", "lectures", "exams"], start=1):
        add_row(db, tmp_path, i, bucket)

    report = LinkStep(kp, db).run("CSE220")

    assert report.added == 3
    assert len(adds(kp)) == 3
    row = db.get("r2")
    assert row.notebook_source_id in kp.sources
    assert row.notebook_id == kp.notebooks["BrightLearn/CSE220"]
    assert row.source_hash == "h2"
    assert row.sync_state == "synced"


def test_second_run_makes_no_calls(db, kp, tmp_path):
    add_row(db, tmp_path, 1, "lectures")
    LinkStep(kp, db).run("CSE220")
    kp.calls.clear()

    report = LinkStep(kp, db).run("CSE220")

    assert kp.calls == []
    assert (report.added, report.replaced, report.deferred) == (0, 0, 0)


def test_stale_row_replaces_its_source(db, kp, tmp_path):
    add_row(db, tmp_path, 1, "lectures")
    LinkStep(kp, db).run("CSE220")
    old = db.get("r1")
    db.upsert(replace(old, hash="h1-v2", sync_state="stale"))
    kp.calls.clear()

    report = LinkStep(kp, db).run("CSE220")

    new = db.get("r1")
    assert [c[0] for c in kp.calls] == ["remove_source", "add_file"]
    assert kp.calls[0][1] == old.notebook_source_id
    assert report.replaced == 1
    assert new.notebook_source_id != old.notebook_source_id
    assert new.source_hash == "h1-v2"
    assert new.sync_state == "synced"


def test_links_are_skipped(db, kp, tmp_path):
    add_row(db, tmp_path, 1, None, state="link")
    assert LinkStep(kp, db).run("CSE220").added == 0
    assert kp.calls == []


def test_only_code_is_skipped_unless_included(db, kp, tmp_path):
    add_row(db, tmp_path, 1, "code")
    add_row(db, tmp_path, 2, "other")  # hand-picked uploads: `other` is a real course file
    add_row(db, tmp_path, 3, "labs")

    assert LinkStep(kp, db).run("CSE220").added == 2
    assert db.get("r1").notebook_source_id is None
    assert db.get("r2").notebook_source_id is not None
    assert LinkStep(kp, db, include_code=True).run("CSE220").added == 1
    assert db.get("r1").notebook_source_id is not None


def test_within_a_bucket_the_oldest_upload_links_first(db, kp, tmp_path):
    # Ids are random hex for new uploads, so they must not decide the order.
    add_row(db, tmp_path, 1, "lectures", added_at="2026-10-02T09:00:00+00:00")
    add_row(db, tmp_path, 2, "lectures", added_at="2026-10-01T09:00:00+00:00")

    LinkStep(kp, db, source_cap=1).run("CSE220")

    assert db.get("r2").notebook_source_id is not None
    assert db.get("r1").sync_state == "deferred"


def test_other_comes_before_included_code_under_the_cap(db, kp, tmp_path):
    add_row(db, tmp_path, 1, "code")
    add_row(db, tmp_path, 2, "other")

    LinkStep(kp, db, source_cap=1, include_code=True).run("CSE220")

    assert db.get("r2").notebook_source_id is not None
    assert db.get("r1").sync_state == "deferred"


def test_cap_keeps_highest_priority_buckets_and_defers_the_rest(db, kp, tmp_path):
    buckets = ["assignments", "labs", "lectures", "syllabus", "readings", "exams"]
    for i, bucket in enumerate(buckets, start=1):
        add_row(db, tmp_path, i, bucket)

    report = LinkStep(kp, db, source_cap=3).run("CSE220")

    rows = [db.get(f"r{i}") for i in range(1, 7)]
    linked = {r.bucket for r in rows if r.notebook_source_id}
    assert linked == {"syllabus", "exams", "lectures"}
    assert {r.bucket for r in rows if r.sync_state == "deferred"} == {
        "readings",
        "labs",
        "assignments",
    }
    assert (report.added, report.deferred) == (3, 3)

    kp.calls.clear()
    LinkStep(kp, db, source_cap=3).run("CSE220")
    assert kp.calls == []


def test_linked_sources_keep_their_slot_when_higher_priority_files_arrive(db, kp, tmp_path):
    add_row(db, tmp_path, 1, "assignments")
    LinkStep(kp, db, source_cap=1).run("CSE220")
    add_row(db, tmp_path, 2, "syllabus")

    LinkStep(kp, db, source_cap=1).run("CSE220")

    assert db.get("r1").notebook_source_id is not None
    assert db.get("r2").sync_state == "deferred"


def test_deferred_rows_link_when_the_cap_allows(db, kp, tmp_path):
    add_row(db, tmp_path, 1, "lectures")
    add_row(db, tmp_path, 2, "lectures")
    LinkStep(kp, db, source_cap=1).run("CSE220")
    assert db.get("r2").sync_state == "deferred"

    LinkStep(kp, db, source_cap=2).run("CSE220")

    assert db.get("r2").sync_state == "synced"
    assert db.get("r2").notebook_source_id is not None


def test_failed_add_is_reported_and_retried(db, kp, tmp_path, monkeypatch):
    add_row(db, tmp_path, 1, "lectures")
    real_add = kp.add_file

    def boom(notebook_id, path):
        raise RuntimeError("quota")

    monkeypatch.setattr(kp, "add_file", boom)
    report = LinkStep(kp, db).run("CSE220")
    assert report.failed == 1
    assert "quota" in report.failures[0]
    assert db.get("r1").notebook_source_id is None

    monkeypatch.setattr(kp, "add_file", real_add)
    assert LinkStep(kp, db).run("CSE220").added == 1


def test_failed_add_after_remove_retries_as_a_new_source(db, kp, tmp_path, monkeypatch):
    add_row(db, tmp_path, 1, "lectures")
    LinkStep(kp, db).run("CSE220")
    db.upsert(replace(db.get("r1"), hash="v2", sync_state="stale"))

    def boom(notebook_id, path):
        raise RuntimeError("upload failed")

    real_add = kp.add_file
    monkeypatch.setattr(kp, "add_file", boom)
    LinkStep(kp, db).run("CSE220")
    assert db.get("r1").notebook_source_id is None
    assert db.get("r1").sync_state == "stale"

    monkeypatch.setattr(kp, "add_file", real_add)
    kp.calls.clear()
    LinkStep(kp, db).run("CSE220")
    assert [c[0] for c in kp.calls] == ["add_file"]
    assert db.get("r1").sync_state == "synced"


def test_rate_limit_stops_the_run(db, kp, tmp_path, monkeypatch):
    for i in range(1, 4):
        add_row(db, tmp_path, i, "lectures")
    attempts = []

    def limited(notebook_id, path):
        attempts.append(path)
        raise KnowledgeRateLimited("quota")

    monkeypatch.setattr(kp, "add_file", limited)
    report = LinkStep(kp, db).run("CSE220")

    assert len(attempts) == 1
    assert "rate limited" in report.failures[0]
    assert all(db.get(f"r{i}").notebook_source_id is None for i in range(1, 4))


def test_notebook_failure_is_reported(db, kp, tmp_path, monkeypatch):
    add_row(db, tmp_path, 1, "lectures")

    def boom(course):
        raise RuntimeError("no auth")

    monkeypatch.setattr(kp, "ensure_notebook", boom)
    report = LinkStep(kp, db).run("CSE220")
    assert report.failures == ["notebook: no auth"]
