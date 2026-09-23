from pathlib import Path

import pytest

from core.config import Config
from core.memory.db import Manifest, connect
from core.providers.lms.base import Course, Resource
from core.sync.engine import SyncEngine
from tests.fakes.lms import FakeLMS
from tests.fakes.storage import FakeStorage

CSE220 = Course(100001, "CSE220", "CSE 220: Systems Fundamentals I")
AMS161 = Course(100002, "AMS161", "AMS 161: Applied Calculus II")
ROOT = "BrightLearn/2026-Fall/CSE220"


def res(topic_id: int, module: str, title: str, kind: str = "File", org: int = 100001) -> Resource:
    return Resource(org, topic_id, module, title, kind, None, "2026-08-25T09:00:00.000Z")


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        home=tmp_path / "home",
        brightspace_base_url="https://mycourses.example.edu",
        term="2026-Fall",
        drive_root="BrightLearn",
        tmp_dir=tmp_path / "tmp",
        db_path=tmp_path / "home" / "brightlearn.db",
    )


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
def manifest(config: Config) -> Manifest:
    return Manifest(connect(config.db_path))


def run(lms, storage, manifest, config, course=None):
    return SyncEngine(lms, storage, manifest, config, now=lambda: "2026-09-23T12:00:00+00:00").run(
        course=course
    )


def test_first_run_lands_files_in_bucket_tree_and_records_links(lms, manifest, config):
    storage = FakeStorage()
    report = run(lms, storage, manifest, config, course="CSE220")

    assert report.courses == ["CSE220"]
    assert (report.uploaded, report.links, report.failed) == (3, 1, 0)
    assert set(storage.files()) == {
        f"{ROOT}/syllabus/CSE220 Syllabus.pdf",
        f"{ROOT}/lectures/lec1.pdf",
        f"{ROOT}/code/helloWorld.c",
    }
    row = manifest.get(5002)
    assert row.sync_state == "synced"
    assert row.drive_bucket == "lectures"
    assert row.drive_file_id == storage.files()[f"{ROOT}/lectures/lec1.pdf"].file_id
    assert manifest.get(5004).sync_state == "link"
    assert manifest.get(5004).drive_file_id is None
    assert manifest.get(6001) is None


def test_second_run_downloads_nothing_and_temp_dir_is_empty(lms, manifest, config):
    storage = FakeStorage()
    run(lms, storage, manifest, config)
    lms.downloads.clear()

    report = run(lms, storage, manifest, config)

    assert lms.downloads == []
    assert report.uploaded == 0
    assert report.unchanged == 4
    assert list(config.tmp_dir.iterdir()) == []


def test_changed_topic_is_reuploaded_in_place(lms, manifest, config):
    storage = FakeStorage()
    run(lms, storage, manifest, config, course="CSE220")
    before = manifest.get(5002)

    lms.touch(5002, "2026-09-01T09:00:00.000Z", content=b"lecture one v2")
    lms.downloads.clear()
    report = run(lms, storage, manifest, config, course="CSE220")

    after = manifest.get(5002)
    assert lms.downloads == [5002]
    assert report.uploaded == 1
    assert after.drive_file_id == before.drive_file_id
    assert after.last_modified == "2026-09-01T09:00:00.000Z"
    assert storage.nodes[after.drive_file_id].content == b"lecture one v2"
    assert storage.nodes[after.drive_file_id].revisions == 2


def test_failed_download_is_recorded_cleaned_up_and_retried(lms, manifest, config):
    storage = FakeStorage()
    lms.fail_topics.add(5003)
    report = run(lms, storage, manifest, config, course="CSE220")

    assert report.failed == 1
    assert report.uploaded == 2
    assert manifest.get(5003).sync_state == "failed"
    assert list(config.tmp_dir.iterdir()) == []

    lms.fail_topics.clear()
    report = run(lms, storage, manifest, config, course="CSE220")
    assert report.uploaded == 1
    assert manifest.get(5003).sync_state == "synced"


def test_md5_mismatch_marks_failed(lms, manifest, config):
    storage = FakeStorage()
    storage.corrupt_uploads = True
    report = run(lms, storage, manifest, config, course="CSE220")
    assert report.failed == 3
    assert "md5 mismatch" in report.errors[0]


def test_same_filename_in_one_bucket_gets_topic_suffix(lms, manifest, config):
    storage = FakeStorage()
    lms.add(res(5010, "Week 2", "Lecture 2"), "lec1.pdf", b"copy-pasted name")
    run(lms, storage, manifest, config, course="CSE220")
    run(lms, storage, manifest, config, course="CSE220")

    assert f"{ROOT}/lectures/lec1.pdf" in storage.files()
    assert f"{ROOT}/lectures/lec1 [5010].pdf" in storage.files()
    assert manifest.get(5002).filename == "lec1.pdf"
    assert manifest.get(5010).filename == "lec1 [5010].pdf"


def test_topic_removed_from_brightspace_keeps_its_row_and_drive_file(lms, manifest, config):
    storage = FakeStorage()
    run(lms, storage, manifest, config, course="CSE220")
    lms.resources[100001] = [r for r in lms.resources[100001] if r.topic_id != 5001]

    run(lms, storage, manifest, config, course="CSE220")

    assert manifest.get(5001).sync_state == "synced"
    assert f"{ROOT}/syllabus/CSE220 Syllabus.pdf" in storage.files()


def test_course_listing_failure_does_not_stop_other_courses(lms, manifest, config):
    lms.fail_courses.add(100001)
    report = run(lms, FakeStorage(), manifest, config)
    assert report.uploaded == 1
    assert report.errors == ["CSE220: could not list resources: HTTP 403"]


def test_unknown_course_filter_raises(lms, manifest, config):
    with pytest.raises(ValueError, match="CSE999"):
        run(lms, FakeStorage(), manifest, config, course="CSE999")


def test_course_filter_accepts_org_unit_id(lms, manifest, config):
    report = run(lms, FakeStorage(), manifest, config, course="100002")
    assert report.courses == ["AMS161"]
