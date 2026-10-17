"""BL-045: course and source routes; an upload is stored by the Importer and linked by a job."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import get_args

from api.engine import Engine, Job, Resources
from api.schemas.sources import SyncState
from core.memory.db import connect
from core.memory.learner import Concept, LearnerMemory
from core.memory.schema import SYNC_STATES
from core.providers.knowledge.base import KnowledgeError


def add_course(client, code: str = "cse220", **extra) -> dict:
    response = client.post("/api/courses", json={"course": code, "name": "Systems", **extra})
    assert response.status_code == 201, response.text
    return response.json()


def upload(client, course: str, *names: str, bucket: str | None = None):
    files = [
        ("files", (name, f"{name} text about pointers".encode(), "application/pdf"))
        for name in names
    ]
    data = {"bucket": bucket} if bucket is not None else {}
    return client.post(f"/api/courses/{course}/sources/upload", files=files, data=data)


@contextmanager
def parked(engine: Engine, kind: str, course: str = "CSE220") -> Iterator[Job]:
    """A job of ``kind`` running on the jobs worker until the block exits."""
    started, release = threading.Event(), threading.Event()

    def wait(r: Resources) -> None:
        started.set()
        release.wait(10)

    job = engine.jobs.submit(kind, course, wait)
    try:
        assert started.wait(10)
        yield job
    finally:
        release.set()
        engine.drain()


def staged(config) -> list:
    return list(config.tmp_dir.iterdir()) if config.tmp_dir.exists() else []


# -- courses ---------------------------------------------------------------------------------


def test_create_and_list_courses(api, config):
    client, *_ = api
    created = add_course(client)
    assert created == {
        "course": "CSE220",  # upper-cased, as the CLI does
        "name": "Systems",
        "term": "Fall-2026",  # config.term
        "created_at": created["created_at"],
        "sources": 0,
        "linked": 0,
        "concepts": 0,
        "open_session_id": None,
    }
    add_course(client, "CSE214", term="Spring-2027")
    conn = connect(config.db_path)
    LearnerMemory(conn).upsert_concept(Concept("CSE220/pointers", "CSE220", "Pointers"))
    conn.close()

    listed = client.get("/api/courses").json()
    assert [(c["course"], c["term"], c["concepts"]) for c in listed] == [
        ("CSE214", "Spring-2027", 0),
        ("CSE220", "Fall-2026", 1),
    ]


def test_counts_follow_uploads_and_links(api):
    client, _, _, engine = api
    add_course(client)
    with parked(engine, "seed"):  # the link job waits behind it
        assert upload(client, "CSE220", "lec3.pdf").status_code == 200
        (course,) = client.get("/api/courses").json()
        assert (course["sources"], course["linked"]) == (1, 0)
    (course,) = client.get("/api/courses").json()
    assert (course["sources"], course["linked"]) == (1, 1)


def test_duplicate_course_is_409(api):
    client, *_ = api
    add_course(client)
    response = client.post("/api/courses", json={"course": "CSE220", "name": "Again"})
    assert response.status_code == 409
    assert response.json()["code"] == "duplicate_course"


def test_a_code_or_term_that_cant_be_a_folder_is_422(api):
    client, *_ = api
    for body in (
        {"course": "CSE 220", "name": "Systems"},
        {"course": "CSE220", "name": "Systems", "term": "../x"},
        {"course": "CSE220", "name": "  "},
    ):
        assert client.post("/api/courses", json=body).status_code == 422, body
    assert client.get("/api/courses").json() == []


def test_an_unknown_course_is_404(api):
    client, *_ = api
    assert client.get("/api/courses/NOPE/sources").status_code == 404
    assert upload(client, "NOPE", "lec3.pdf").status_code == 404
    assert client.post("/api/courses/NOPE/sources/link").status_code == 404


# -- uploads ---------------------------------------------------------------------------------


def test_uploads_are_stored_by_bucket_and_linked_by_the_job(api, config):
    client, kp, _, engine = api
    add_course(client)

    classified = upload(client, "cse220", "lec3.pdf")
    assert classified.status_code == 200, classified.text
    body = classified.json()
    (row,) = body["imported"]
    assert (row["filename"], row["bucket"], row["sync_state"], row["linked"]) == (
        "lec3.pdf",
        "lectures",
        "synced",
        False,
    )
    assert body["job"]["kind"] == "link" and body["job"]["course"] == "CSE220"
    assert staged(config) == []
    engine.drain()

    chosen = upload(client, "CSE220", "policy.pdf", bucket="syllabus")
    assert chosen.json()["imported"][0]["bucket"] == "syllabus"
    assert staged(config) == []
    engine.drain()

    root = config.storage_root.resolve() / "Fall-2026" / "CSE220"
    added = [path for call, path in kp.calls if call == "add_file"]
    assert added == [root / "lectures" / "lec3.pdf", root / "syllabus" / "policy.pdf"]
    assert all(path.is_file() for path in added)
    sources = client.get("/api/courses/CSE220/sources").json()
    # Upload order, but both may carry the same second: compare as a set.
    assert {(s["filename"], s["bucket"], s["linked"]) for s in sources} == {
        ("lec3.pdf", "lectures", True),
        ("policy.pdf", "syllabus", True),
    }
    assert all(s["notebook_source_id"] for s in sources)
    job = client.get(f"/api/jobs/{chosen.json()['job']['id']}").json()
    assert job["status"] == "done"
    assert job["result"] == {
        "course": "CSE220",
        "added": 1,
        "replaced": 0,
        "deferred": 0,
        "failed": 0,
        "failures": [],
    }


def test_an_unknown_bucket_is_422_and_stores_nothing(api, config):
    client, kp, _, engine = api
    add_course(client)
    response = upload(client, "CSE220", "lec3.pdf", "lec4.pdf", bucket="memes")
    assert response.status_code == 422
    assert "Unknown bucket 'memes'" in response.json()["detail"]
    assert client.get("/api/courses/CSE220/sources").json() == []
    assert staged(config) == []
    assert engine.jobs.all() == []
    assert not (config.storage_root / "Fall-2026" / "CSE220").exists()


def test_an_upload_refuses_while_a_link_job_runs(api, config):
    """The link step writes back the rows it read when it started, so it would undo an import."""
    client, _, _, engine = api
    add_course(client)
    with parked(engine, "link") as job:
        response = upload(client, "CSE220", "lec3.pdf")
        assert response.status_code == 409
        assert response.json()["code"] == "job_running"
        assert (response.json()["job_id"], response.json()["kind"]) == (job.id, "link")
        assert client.get("/api/courses/CSE220/sources").json() == []
        assert staged(config) == []
    # Other kinds of job, and link jobs on other courses, don't block it.
    with parked(engine, "seed"):
        assert upload(client, "CSE220", "lec3.pdf").status_code == 200
    with parked(engine, "link", "CSE214"):
        assert upload(client, "CSE220", "lec4.pdf").status_code == 200


@contextmanager
def held(engine: Engine) -> Iterator[None]:
    """The jobs worker busy with a job that isn't the course's, so the next one stays queued."""
    with parked(engine, "podcast", "CSE214"):
        yield


def test_an_upload_refuses_while_a_link_job_is_only_queued(api, config):
    client, _, _, engine = api
    add_course(client)
    with held(engine):
        queued = client.post("/api/courses/CSE220/sources/link").json()
        assert engine.jobs.get(queued["id"]).status == "queued"

        response = upload(client, "CSE220", "lec3.pdf")

        assert response.status_code == 409
        assert (response.json()["code"], response.json()["job_id"]) == ("job_running", queued["id"])
        assert client.get("/api/courses/CSE220/sources").json() == []
        assert staged(config) == []


def test_retry_returns_the_link_job_already_queued_or_running(api):
    client, _, _, engine = api
    add_course(client)
    with held(engine):
        first = client.post("/api/courses/CSE220/sources/link")
        again = client.post("/api/courses/CSE220/sources/link")
        assert first.status_code == again.status_code == 200
        assert again.json() == first.json() and first.json()["status"] == "queued"
    assert [j.kind for j in engine.jobs.all("CSE220")] == ["link"]

    with parked(engine, "link") as running:
        response = client.post("/api/courses/CSE220/sources/link")
        assert response.json()["id"] == running.id and response.json()["status"] == "running"
    after = client.post("/api/courses/CSE220/sources/link")  # none active: a new one
    assert after.json()["id"] not in {first.json()["id"], running.id}
    engine.drain()


def test_a_name_too_long_to_store_is_422(api, config):
    client, _, _, engine = api
    add_course(client)
    long_name = "é" * 126 + ".pdf"  # 256 bytes of UTF-8, 130 characters

    response = upload(client, "CSE220", long_name)

    assert response.status_code == 422 and "too long" in response.json()["detail"]
    assert client.get("/api/courses/CSE220/sources").json() == []
    assert staged(config) == [] and engine.jobs.all() == []
    assert upload(client, "CSE220", "é" * 125 + ".pdf").status_code == 200  # 254 bytes
    engine.drain()


def test_a_failure_mid_list_keeps_the_files_before_it(api, config):
    client, kp, _, engine = api
    add_course(client)

    response = upload(client, "CSE220", "lec3.pdf", "x" * 252 + ".pdf", "lec4.pdf")

    assert response.status_code == 422
    (stored,) = client.get("/api/courses/CSE220/sources").json()
    assert (stored["filename"], stored["linked"]) == ("lec3.pdf", False)
    assert staged(config) == []
    assert engine.jobs.all() == []  # no link job; the retry picks the stored file up
    client.post("/api/courses/CSE220/sources/link")
    engine.drain()
    assert [s["linked"] for s in client.get("/api/courses/CSE220/sources").json()] == [True]


def test_a_new_version_whose_kept_copy_would_be_too_long_is_422(api, config):
    """Within the limit, but its ``_versions`` copy (name plus nine bytes) would not be."""
    client, _, _, engine = api
    add_course(client)
    name = "x" * 246 + ".pdf"  # 250 bytes
    assert upload(client, "CSE220", name).status_code == 200
    engine.drain()

    files = [("files", (name, b"a corrected lecture", "application/pdf"))]
    response = client.post("/api/courses/CSE220/sources/upload", files=files)

    assert response.status_code == 422 and "too long" in response.json()["detail"]
    (stored,) = config.storage_root.glob("Fall-2026/CSE220/*/x*.pdf")
    assert stored.read_bytes() == f"{name} text about pointers".encode()  # the old one, intact
    (row,) = client.get("/api/courses/CSE220/sources").json()
    assert (row["sync_state"], row["linked"]) == ("synced", True)
    assert staged(config) == []


def test_retrying_the_link_job_links_what_failed(api, monkeypatch):
    client, kp, _, engine = api
    add_course(client)
    real_add_file = kp.add_file
    failures = iter([KnowledgeError("upload refused")])

    def flaky_add_file(notebook_id, path):
        failure = next(failures, None)
        if failure is not None:
            raise failure
        return real_add_file(notebook_id, path)

    monkeypatch.setattr(kp, "add_file", flaky_add_file)
    first = upload(client, "CSE220", "lec3.pdf", "lec4.pdf").json()["job"]
    engine.drain()
    result = client.get(f"/api/jobs/{first['id']}").json()["result"]
    assert (result["added"], result["failed"]) == (1, 1)
    assert "upload refused" in result["failures"][0]
    # Which of the two failed depends on their random ids: same bucket, same second.
    linked = [s["linked"] for s in client.get("/api/courses/CSE220/sources").json()]
    assert sorted(linked) == [False, True]

    retry = client.post("/api/courses/CSE220/sources/link")
    assert retry.status_code == 200 and retry.json()["kind"] == "link"
    engine.drain()
    assert client.get(f"/api/jobs/{retry.json()['id']}").json()["result"]["added"] == 1
    linked = [s["linked"] for s in client.get("/api/courses/CSE220/sources").json()]
    assert linked == [True, True]


def test_sync_state_type_matches_the_table():
    assert get_args(SyncState) == SYNC_STATES
