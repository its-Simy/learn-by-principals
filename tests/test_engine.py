import hashlib
from dataclasses import replace

import pytest

from core.config import Config
from core.memory.db import Manifest, connect
from core.providers.lms.base import Course, Resource
from core.providers.storage.local import LocalStorageBackend
from core.sync.engine import SyncEngine, select_courses
from tests.fakes.lms import FakeLMS

CSE220 = Course(100001, "CSE220", "CSE 220: Systems Fundamentals I")
AMS161 = Course(100002, "AMS161", "AMS 161: Applied Calculus II")
TERM = "Fall-2026"


def res(topic_id: int, module: str, title: str, kind: str = "File", org: int = 100001) -> Resource:
    url = "https://zoom.example/rec" if kind == "Link" else None
    return Resource(org, topic_id, module, title, kind, url, "2026-08-25T09:00:00.000Z")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def lms() -> FakeLMS:
    lms = FakeLMS([CSE220, AMS161])
    lms.add(res(5001, "Course Information", "Syllabus"), "CSE220 Syllabus.pdf", b"syllabus")
    lms.add(res(5002, "Week 1", "Lecture 1"), "lec1.pdf", b"lecture one")
    lms.add(res(5003, "Week 1", "helloWorld"), "helloWorld.c", b"int main;")
    lms.add(res(5004, "Week 1", "Zoom recording", kind="Link"))
    lms.add(res(6001, "Week 1", "Lecture 1", org=100002), "lec1.pdf", b"calc")
    return lms


@pytest.fixture
def db(config: Config) -> Manifest:
    return Manifest(connect(config.db_path))


@pytest.fixture
def storage(config: Config) -> LocalStorageBackend:
    return LocalStorageBackend(config.storage_root)


@pytest.fixture
def sync(lms, storage, db, config):
    engine = SyncEngine(lms, storage, db, config, now=lambda: "2026-09-23T12:00:00+00:00")

    def run(course=CSE220, **kwargs):
        return engine.sync_course(course, TERM, **kwargs)

    return run


def course_root(config: Config):
    return config.storage_root / TERM / "CSE220"


def stored_files(config: Config) -> set[str]:
    root = course_root(config)
    return (
        {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        if root.exists()
        else set()
    )


def tmp_is_empty(config: Config) -> bool:
    return not config.tmp_dir.exists() or list(config.tmp_dir.iterdir()) == []


def test_first_run_stores_new_files_in_bucket_tree_and_records_links(sync, db, config):
    report = sync()

    assert (report.new, report.changed, report.skipped, report.links, report.failed) == (
        3,
        0,
        0,
        1,
        0,
    )
    assert stored_files(config) == {
        "syllabus/CSE220 Syllabus.pdf",
        "lectures/lec1.pdf",
        "code/helloWorld.c",
    }
    row = db.get(5002)
    assert row.sync_state == "synced"
    assert row.bucket == "lectures"
    assert row.local_path == str(course_root(config).resolve() / "lectures" / "lec1.pdf")
    assert row.hash == sha(b"lecture one")
    assert row.size == len(b"lecture one")
    link = db.get(5004)
    assert link.sync_state == "link"
    assert link.url == "https://zoom.example/rec"
    assert link.local_path is None
    assert db.get(6001) is None
    assert tmp_is_empty(config)


def test_second_run_downloads_nothing(sync, lms, config):
    sync()
    lms.downloads.clear()

    report = sync()

    assert lms.downloads == []
    assert (report.new, report.changed, report.skipped, report.links) == (0, 0, 3, 1)
    assert tmp_is_empty(config)


def test_changed_bytes_mark_the_row_stale_and_overwrite_the_file(sync, lms, db, config):
    sync()
    lms.touch(5002, "2026-09-01T09:00:00.000Z", content=b"lecture one v2")
    lms.downloads.clear()

    report = sync()

    row = db.get(5002)
    assert lms.downloads == [5002]
    assert (report.new, report.changed, report.skipped) == (0, 1, 2)
    assert row.sync_state == "stale"
    assert row.hash == sha(b"lecture one v2")
    assert row.last_modified == "2026-09-01T09:00:00.000Z"
    assert (course_root(config) / "lectures" / "lec1.pdf").read_bytes() == b"lecture one v2"
    assert [r.topic_id for r in db.all(states=["stale"])] == [5002]
    assert tmp_is_empty(config)


def test_changed_timestamp_with_identical_bytes_stays_synced(sync, lms, db):
    sync()
    lms.touch(5002, "2026-09-01T09:00:00.000Z")
    lms.downloads.clear()

    report = sync()

    assert lms.downloads == [5002]
    assert report.changed == 0
    assert db.get(5002).sync_state == "synced"
    assert db.get(5002).last_modified == "2026-09-01T09:00:00.000Z"


def test_stale_row_stays_stale_until_relinked(sync, lms, db):
    sync()
    lms.touch(5002, "2026-09-01T09:00:00.000Z", content=b"v2")
    sync()
    lms.touch(5002, "2026-09-02T09:00:00.000Z")  # new timestamp, same v2 bytes

    sync()

    assert db.get(5002).sync_state == "stale"


def test_deferred_rows_are_not_redownloaded(sync, lms, db):
    sync()
    db.upsert(replace(db.get(5002), sync_state="deferred"))
    lms.downloads.clear()

    sync()

    assert lms.downloads == []
    assert db.get(5002).sync_state == "deferred"


def test_session_expired_once_is_retried_after_ensure_session(sync, lms, db):
    lms.session_expired = True

    report = sync()

    assert lms.sessions_ensured == 1
    assert report.new == 3
    assert report.failed == 0


def test_session_expired_during_download_is_retried(sync, lms, db):
    sync()
    lms.touch(5002, "2026-09-01T09:00:00.000Z", content=b"v2")
    lms.session_expired = True
    lms.downloads.clear()

    report = sync()

    assert lms.sessions_ensured == 1
    assert lms.downloads == [5002]
    assert report.changed == 1


def test_session_that_stays_expired_fails_the_resource(sync, lms, db, config):
    sync()
    lms.touch(5002, "2026-09-01T09:00:00.000Z", content=b"v2")
    lms.session_expired = True
    lms.relogin_works = False
    real_list = lms.list_resources
    lms.list_resources = lambda org: lms.resources[org]  # listing succeeds, downloads fail

    report = sync()

    lms.list_resources = real_list
    assert report.failed == 1
    assert db.get(5002).sync_state == "failed"
    assert tmp_is_empty(config)


def test_failed_download_is_recorded_cleaned_up_and_retried(sync, lms, db, config):
    lms.fail_topics.add(5003)
    report = sync()

    assert (report.new, report.failed) == (2, 1)
    assert "connection reset" in report.failures[0]
    assert db.get(5003).sync_state == "failed"
    assert tmp_is_empty(config)

    lms.fail_topics.clear()
    report = sync()
    assert report.new == 1
    assert db.get(5003).sync_state == "synced"


def test_dry_run_touches_nothing(sync, lms, db, config):
    report = sync(dry_run=True)

    assert (report.new, report.links) == (3, 1)
    assert lms.downloads == []
    assert db.all() == []
    assert not config.storage_root.exists()
    assert not config.tmp_dir.exists()


def test_dry_run_after_a_change_reports_it_without_downloading(sync, lms, db):
    sync()
    lms.touch(5002, "2026-09-01T09:00:00.000Z", content=b"v2")
    lms.downloads.clear()
    before = db.all()

    report = sync(dry_run=True)

    assert (report.new, report.changed, report.skipped) == (0, 1, 2)
    assert lms.downloads == []
    assert db.all() == before


def test_force_redownloads_current_files(sync, lms, db):
    sync()
    lms.downloads.clear()

    report = sync(force=True)

    assert sorted(lms.downloads) == [5001, 5002, 5003]
    assert report.skipped == 3
    assert db.get(5002).sync_state == "synced"


def test_same_filename_in_one_bucket_gets_topic_suffix(sync, lms, db, config):
    lms.add(res(5010, "Week 2", "Lecture 2"), "lec1.pdf", b"copy-pasted name")
    sync()
    sync()

    assert {"lectures/lec1.pdf", "lectures/lec1 [5010].pdf"} <= stored_files(config)
    assert db.get(5002).filename == "lec1.pdf"
    assert db.get(5010).filename == "lec1 [5010].pdf"


def test_topic_removed_from_brightspace_keeps_its_row_and_file(sync, lms, db, config):
    sync()
    lms.resources[100001] = [r for r in lms.resources[100001] if r.topic_id != 5001]

    sync()

    assert db.get(5001).sync_state == "synced"
    assert "syllabus/CSE220 Syllabus.pdf" in stored_files(config)


def test_course_listing_failure_is_reported(sync, lms):
    lms.fail_courses.add(100001)
    report = sync()
    assert report.failures == ["could not list resources: HTTP 403"]


def test_select_courses():
    courses = [CSE220, AMS161]
    assert select_courses(courses, None) == courses
    assert select_courses(courses, "cse220") == [CSE220]
    assert select_courses(courses, "100002") == [AMS161]
    assert select_courses(courses, "CSE999") == []
