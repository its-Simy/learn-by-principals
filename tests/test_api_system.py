"""BL-044: system routes, the error mapping, the static mount and ``brightlearn web``."""

import json
from datetime import datetime, timedelta
from importlib.metadata import version

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from api.app import create_app, protect, register_errors
from api.deps import course_code
from api.engine import Job, JobRunning
from api.errors import Conflict, Refused
from api.static import NOT_BUILT, mount_web
from cli.app import app as cli
from core import personas
from core.config import load_config
from core.doctor import Check, Status
from core.memory.db import Courses, DuplicateCourse, connect
from core.memory.learner import SessionRow
from core.memory.schema import SCHEMA_VERSION
from core.providers.knowledge.base import KnowledgeError
from core.providers.models.base import ModelRateLimited, UsageHint
from core.router.router import NoProvider
from core.sessions import SessionOpen
from tests.test_dashboard import NOW, seed


def test_health(api):
    client, *_ = api
    assert client.get("/api/health").json() == {
        "ok": True,
        "version": version("brightlearn"),
        "schema_version": SCHEMA_VERSION,
        "term": "Fall-2026",  # config.term, which the new-course dialog prefills
    }


def test_personas(api):
    client, *_ = api
    body = client.get("/api/personas").json()
    assert [p["name"] for p in body] == personas.list_personas()
    simplifier = next(p for p in body if p["name"] == "simplifier")
    assert simplifier["group"] == "teaching" and simplifier["task_types"]


def test_dashboard_from_seeded_data(api, config):
    client, *_ = api
    conn = connect(config.db_path)
    seed(conn)
    conn.close()

    body = client.get("/api/dashboard").json()
    claude = next(h for h in body["health"] if h["provider"] == "claude")
    assert claude["state"] == "RATE_LIMITED" and claude["detail"] == "usage limit reached"
    assert datetime.fromisoformat(claude["cooldown_until"]) == NOW + timedelta(minutes=55)
    (mark,) = body["benchmarks"]
    assert (mark["provider"], mark["task_type"], mark["sample_count"]) == (
        "codex",
        "question_gen",
        12,
    )
    assert mark["accuracy"] == 0.75 and mark["score"] == pytest.approx(0.75)
    assert body["artifacts_total"] == {"Audio overviews": 2, "Quizzes": 1, "Other artifacts": 0}
    assert body["podcasts"] == 1
    assert body["sync"] == {
        "CSE220": {"synced": 7, "stale": 2, "failed": 1, "link": 3, "deferred": 1}
    }
    assert body["weakest"][0] == {
        "course": "CSE220",
        "name": "Pointers",
        "level": 0,
        "confidence": 0.0,
        "retention": None,
    }
    assert [w["name"] for w in body["weakest"]][-1] == "Bitwise operators"
    assert {"today", "week", "artifacts_week", "generated_at"} <= set(body)


def test_doctor_runs_the_checks(api, monkeypatch):
    client, *_ = api

    def boom() -> Check:
        raise RuntimeError("kaput")

    canned = [
        ("Config", lambda: Check("Config", Status.OK, "fine")),
        ("Later", lambda: Check("Later", Status.OFF, "arrives later")),
        ("Boom", boom),
    ]
    monkeypatch.setattr("core.doctor.checks", lambda config: canned)
    assert client.get("/api/doctor").json() == [
        {"name": "Config", "status": "ok", "detail": "fine"},
        {"name": "Later", "status": "not configured", "detail": "arrives later"},
        {"name": "Boom", "status": "fail", "detail": "RuntimeError: kaput"},
    ]


def test_jobs(api):
    client, _, _, engine = api
    job = engine.jobs.submit("link", "CSE220", lambda r: {"linked": 2})
    engine.jobs.submit("seed", "CSE221", lambda r: None)
    engine.drain()

    listed = client.get("/api/jobs", params={"course": "cse220"}).json()
    assert [(j["id"], j["kind"], j["status"]) for j in listed] == [(job.id, "link", "done")]
    assert len(client.get("/api/jobs").json()) == 2
    one = client.get(f"/api/jobs/{job.id}").json()
    assert one["result"] == {"linked": 2} and one["error"] is None and one["finished_at"]
    missing = client.get("/api/jobs/nope")
    assert missing.status_code == 404 and "forgotten" in missing.json()["detail"]


def test_unknown_api_paths_are_json_404s(api):
    client, *_ = api
    for method, path in [("GET", "/api/nope"), ("POST", "/api/nope"), ("GET", "/api")]:
        response = client.request(method, path)
        assert response.status_code == 404, (method, path)
        assert response.json()["detail"] == f"No API route {path}"


def test_a_known_api_path_with_the_wrong_method_is_405(api):
    client, *_ = api
    response = client.post("/api/health")
    assert response.status_code == 405 and response.headers["allow"] == "GET"


# -- other sites' pages ---------------------------------------------------------------------


@pytest.fixture
def guarded() -> TestClient:
    app = FastAPI()
    protect(app)

    @app.get("/read")
    def read() -> dict:
        return {"ok": True}

    @app.post("/write")
    def write() -> dict:
        return {"ok": True}

    return TestClient(app, base_url="http://127.0.0.1:8765")


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({}, 200),  # not a browser: curl, a script, TestClient's defaults
        ({"Sec-Fetch-Site": "same-origin", "Origin": "http://127.0.0.1:8765"}, 200),
        ({"Sec-Fetch-Site": "none"}, 200),  # typed into the address bar
        ({"Origin": "http://localhost:5173"}, 200),  # the Vite dev server
        ({"Origin": "https://evil.example"}, 403),
        ({"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"}, 403),
        ({"Sec-Fetch-Site": "cross-site"}, 403),
        ({"Origin": "null"}, 403),  # a sandboxed frame or a file:// page
        ({"Origin": "http://[::1"}, 403),
    ],
)
def test_writes_only_from_our_own_pages(guarded, headers, status):
    response = guarded.post("/write", headers=headers)
    assert response.status_code == status, response.text
    if status == 403:
        assert response.json()["code"] == "cross_origin"


def test_reads_are_not_origin_checked_but_hosts_are(guarded):
    assert guarded.get("/read", headers={"Origin": "https://evil.example"}).status_code == 200
    assert guarded.get("/read", headers={"Host": "localhost:8765"}).status_code == 200
    rebound = guarded.get("/read", headers={"Host": "evil.example"})  # DNS rebinding
    assert rebound.status_code == 400


def test_the_app_is_guarded(api):
    client, *_ = api
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
    evil = client.post("/api/jobs", headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    assert client.post("/api/jobs").status_code == 405  # past the guard, to the router


# -- the error mapping ----------------------------------------------------------------------


@pytest.fixture
def raising() -> TestClient:
    """A bare app with ``register_errors``: each route raises one core exception."""
    session = SessionRow("s1", "CSE220", "2026-09-23T10:00:00+00:00")
    job = Job("j1", "seed", "CSE220", "2026-09-23T10:00:00+00:00", status="running")
    errors = {
        "session": SessionOpen(session, stale=True),
        "job": JobRunning(job),
        "duplicate": DuplicateCourse("course CSE220 already exists"),
        "conflict": Conflict("session_live", "Session s1 is live", session_id="s1"),
        "value": ValueError("unknown bucket 'misc'"),
        "refused": Refused("nothing_linked", "Nothing from CSE220 is in NotebookLM yet"),
        "spec": personas.PersonaError("No persona 'x'"),
        "limited": ModelRateLimited("claude: usage limit", UsageHint(resets_at="3pm")),
        "noprovider": NoProvider("No model provider left for explain: claude is RATE_LIMITED"),
        "knowledge": KnowledgeError("notebook gone"),
        "missing": FileNotFoundError("no transcript s9"),
    }
    errors["limited"].provider = "claude"
    app = FastAPI()
    register_errors(app)

    @app.get("/raise/{name}")
    def raise_(name: str) -> None:
        raise errors[name]

    @app.get("/http")
    def http() -> None:
        raise HTTPException(404, "plain")

    return TestClient(app)


@pytest.mark.parametrize(
    ("name", "status", "body"),
    [
        ("session", 409, {"code": "session_open", "session_id": "s1", "stale": True}),
        ("job", 409, {"code": "job_running", "job_id": "j1", "kind": "seed"}),
        ("duplicate", 409, {"code": "duplicate_course"}),
        (
            "conflict",
            409,
            {"code": "session_live", "detail": "Session s1 is live", "session_id": "s1"},
        ),
        ("value", 422, {"detail": "unknown bucket 'misc'"}),
        (
            "refused",
            422,
            {"code": "nothing_linked", "detail": "Nothing from CSE220 is in NotebookLM yet"},
        ),
        ("spec", 422, {"detail": "No persona 'x'"}),
        ("limited", 502, {"provider": "claude", "resets_at": "3pm"}),
        ("noprovider", 502, {"provider": None, "resets_at": None}),
        ("knowledge", 502, {"provider": "notebooklm", "detail": "notebook gone"}),
        ("missing", 404, {"detail": "no transcript s9"}),
    ],
)
def test_errors_map_to_statuses(raising, name, status, body):
    response = raising.get(f"/raise/{name}")
    assert response.status_code == status
    assert body.items() <= response.json().items()
    assert response.json()["detail"]


def test_session_open_says_why(raising):
    detail = raising.get("/raise/session").json()["detail"]
    assert "s1" in detail and "stale" in detail


def test_one_text_model_for_every_router(config):
    """Chat and the Studio both send and take plain text; the web types should have one shape."""
    schemas = create_app(config).openapi()["components"]["schemas"]
    assert [name for name in schemas if "Text" in name] == ["TextIn", "TextOut"]


def test_course_code_upper_cases_and_404s(config):
    conn = connect(config.db_path)
    Courses(conn).add("CSE220", "Systems", "Fall-2026")
    assert course_code("cse220", conn) == "CSE220"
    with pytest.raises(HTTPException) as caught:
        course_code("cse999", conn)
    assert caught.value.status_code == 404 and "CSE999" in caught.value.detail
    conn.close()


# -- the static mount -----------------------------------------------------------------------


def web_client(dist) -> TestClient:
    app = FastAPI()
    mount_web(app, dist)
    return TestClient(app)


def test_without_a_build_every_page_says_how_to_build(tmp_path):
    client = web_client(tmp_path / "dist")
    for path in ("/", "/courses/CSE220"):
        response = client.get(path)
        assert response.status_code == 200 and response.text == NOT_BUILT
        assert response.headers["content-type"].startswith("text/plain")
    assert "pnpm --dir web build" in NOT_BUILT and NOT_BUILT.count("\n") == 1
    assert client.get("/api/nope").status_code == 404


def test_a_build_serves_files_and_the_spa_for_deep_links(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>BrightLearn</title>")
    (dist / "assets" / "x.js").write_text("console.log('x')")
    (dist / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("not for you")
    client = web_client(dist)

    for path in ("/", "/index.html", "/courses/X", "/courses/X/exams/e1/take"):
        page = client.get(path)
        assert "<title>BrightLearn</title>" in page.text, path
        assert page.headers["cache-control"] == "no-cache", path  # it names this build's bundles
    asset = client.get("/assets/x.js")
    assert asset.text == "console.log('x')" and "javascript" in asset.headers["content-type"]
    assert client.get("/favicon.svg").text == "<svg/>"
    assert client.get("/assets/missing.js").status_code == 404
    assert "not for you" not in client.get("/..%2fsecret.txt").text
    assert client.get("/%00").status_code == 404
    api = client.get("/api/nope")
    assert api.status_code == 404 and api.json()["detail"] == "No API route /api/nope"


# -- the CLI --------------------------------------------------------------------------------


def test_web_runs_uvicorn_on_localhost(monkeypatch):
    runs, timers = [], []
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: runs.append((a, kw)))

    class FakeTimer:
        def __init__(self, interval, fn, args):
            timers.append((interval, fn, args))
            self.daemon = False

        def start(self) -> None:
            assert self.daemon

    monkeypatch.setattr("cli.web.threading.Timer", FakeTimer)
    result = CliRunner().invoke(cli, ["web", "--no-open", "--port", "8799"])
    assert result.exit_code == 0, result.output
    assert runs == [
        (
            ("api.app:create_app",),
            {
                "factory": True,
                "host": "127.0.0.1",
                "port": 8799,
                "log_config": None,
                "timeout_graceful_shutdown": 2,
            },
        )
    ]
    assert timers == []
    assert CliRunner().invoke(cli, ["web"]).exit_code == 0
    assert timers[0][0] == 1.0 and timers[0][2] == ("http://127.0.0.1:8765/",)


def test_dev_openapi_prints_the_contract_without_side_effects():
    result = CliRunner().invoke(cli, ["dev", "openapi"])
    assert result.exit_code == 0, result.output
    document = json.loads(result.output)
    assert {"/api/health", "/api/dashboard", "/api/jobs/{job_id}"} <= set(document["paths"])
    assert not load_config().home.exists()  # building the app opened nothing
