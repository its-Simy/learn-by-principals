"""GeminiNotebookProvider with mocked transports and a mocked notebooklm-py client; no network."""

import enum
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.memory.db import Manifest, ResourceRow, connect
from core.providers.knowledge import gemini_notebook as gn
from core.providers.knowledge.base import (
    Conversation,
    GroundedAnswer,
    KnowledgeError,
    KnowledgeRateLimited,
    ProviderState,
    SourceMeta,
)
from core.providers.knowledge.gemini_notebook import GeminiNotebookProvider


# Stand-ins for notebooklm-py's exceptions: the provider classifies by class name.
class NotebookLMError(Exception):
    pass


class RPCError(NotebookLMError):
    pass


class RateLimitError(RPCError):
    pass


class AuthError(RPCError):
    pass


class NotFoundError(NotebookLMError):
    pass


@dataclass
class FakeTransport:
    name: str
    fail_with: Exception | None = None
    calls: list[str] = field(default_factory=list)
    notebooks: dict[str, str] = field(default_factory=dict)

    async def _step(self, call: str) -> None:
        self.calls.append(call)
        if self.fail_with is not None:
            raise self.fail_with

    async def list_notebooks(self):
        await self._step("list_notebooks")
        return [(i, t) for t, i in self.notebooks.items()]

    async def find_or_create_notebook(self, title):
        await self._step("find_or_create_notebook")
        return self.notebooks.setdefault(title, f"nb-{len(self.notebooks) + 1}")

    async def add_file(self, notebook_id, path):
        await self._step("add_file")
        return f"src-{self.name}-{len(self.calls)}"

    async def delete_source(self, notebook_id, source_id):
        await self._step(f"delete_source {notebook_id} {source_id}")

    async def list_sources(self, notebook_id):
        await self._step("list_sources")
        return [SourceMeta("s9", "lec1.pdf", "pdf", None)]

    async def refresh_source(self, notebook_id, source_id):
        await self._step("refresh_source")

    async def ask(self, notebook_id, question, source_ids, conversation_id):
        await self._step("ask")
        return GroundedAnswer(f"answer from {self.name}", [], conversation_id or "conv-new")

    async def fulltext(self, notebook_id, source_id):
        await self._step("fulltext")
        return "full text"

    async def generate(self, notebook_id, kind, options, dest: Path, timeout_s):
        await self._step(f"generate {kind}")
        dest.write_text(json.dumps({"questions": [{"question": "Q?"}]}))
        return dest

    async def close(self):
        pass


class Clock:
    def __init__(self):
        self.t = 100.0
        self.sleeps: list[float] = []

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


@pytest.fixture
def conn():
    return connect(":memory:")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def android():
    return FakeTransport("android")


@pytest.fixture
def web():
    return FakeTransport("web")


@pytest.fixture
def provider(conn, android, web, tmp_path, clock):
    p = GeminiNotebookProvider(
        conn, [android, web], out_dir=tmp_path / "out", clock=clock, sleep=clock.sleep
    )
    yield p
    p.close()


def runs(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM model_runs ORDER BY rowid")]


def test_android_success_is_available_and_logged(provider, conn, android, web):
    source_id = provider.add_file("nb-1", Path("lec1.pdf"))

    assert source_id.startswith("src-android")
    assert provider.state is ProviderState.AVAILABLE
    assert web.calls == []
    (run,) = runs(conn)
    assert (run["provider"], run["model"], run["task_type"], run["success"]) == (
        "notebooklm",
        "android",
        "add_file",
        1,
    )
    assert run["fallback_from"] is None
    assert run["duration_ms"] is not None


def test_android_failure_retries_once_on_web_and_marks_limited(provider, conn, android, web):
    android.fail_with = RPCError("grpc UNAVAILABLE")

    answer = provider.query("nb-1", "What is a pointer?")

    assert answer.text == "answer from web"
    assert android.calls == ["ask"]
    assert web.calls == ["ask"]
    assert provider.state is ProviderState.LIMITED
    (run,) = runs(conn)
    assert (run["model"], run["fallback_from"], run["success"]) == ("web", "android", 1)
    assert run["input_tokens_est"] > 0 and run["output_tokens_est"] > 0


def test_both_failing_is_broken(provider, conn, android, web):
    android.fail_with = RPCError("android down")
    web.fail_with = RPCError("web down")

    with pytest.raises(KnowledgeError, match="web down"):
        provider.list_sources("nb-1")

    assert provider.state is ProviderState.BROKEN
    (run,) = runs(conn)
    assert run["success"] == 0
    assert "RPCError: web down" in run["error"]


def test_both_failing_auth_is_auth_expired(provider, android, web):
    android.fail_with = AuthError("bearer mint failed")
    web.fail_with = AuthError("cookies expired")
    with pytest.raises(KnowledgeError):
        provider.list_sources("nb-1")
    assert provider.state is ProviderState.AUTH_EXPIRED


def test_rate_limit_does_not_fall_back(provider, android, web):
    android.fail_with = RateLimitError("RESOURCE_EXHAUSTED")

    with pytest.raises(KnowledgeRateLimited):
        provider.query("nb-1", "q")

    assert web.calls == []
    assert provider.state is ProviderState.RATE_LIMITED


def test_caller_error_does_not_fall_back_or_change_state(provider, android, web):
    android.fail_with = NotFoundError("no such notebook")
    with pytest.raises(KnowledgeError, match="no such notebook"):
        provider.list_sources("nb-x")
    assert web.calls == []
    assert provider.state is ProviderState.AVAILABLE


def test_state_recovers_when_android_works_again(provider, android):
    android.fail_with = RPCError("blip")
    provider.list_sources("nb-1")
    assert provider.state is ProviderState.LIMITED

    android.fail_with = None
    provider.list_sources("nb-1")
    assert provider.state is ProviderState.AVAILABLE


def test_calls_are_spaced_by_the_minimum_interval(provider, clock):
    provider.list_sources("nb-1")
    clock.t += 0.5
    provider.list_sources("nb-1")
    assert clock.sleeps == [pytest.approx(1.0)]


def test_fallback_attempt_is_also_paced(provider, android, clock):
    android.fail_with = RPCError("down")
    provider.list_sources("nb-1")
    assert clock.sleeps == [pytest.approx(1.5)]


def test_ensure_notebook_finds_or_creates_once_then_uses_the_table(provider, conn, android):
    notebook_id = provider.ensure_notebook("CSE220")

    assert android.notebooks == {"BrightLearn/CSE220": notebook_id}
    assert conn.execute("SELECT notebook_id FROM notebooks WHERE course = 'CSE220'").fetchone()[0]
    android.calls.clear()
    assert provider.ensure_notebook("CSE220") == notebook_id
    assert android.calls == []


def test_remove_source_knows_the_notebook_from_add_file(provider, android):
    source_id = provider.add_file("nb-7", Path("lec1.pdf"))
    provider.remove_source(source_id)
    assert android.calls[-1] == f"delete_source nb-7 {source_id}"


def test_remove_source_falls_back_to_the_manifest(provider, conn, android):
    Manifest(conn).upsert(
        ResourceRow(
            course="CSE220",
            org_unit_id=1,
            topic_id=1,
            module_path="",
            title="",
            type_identifier="File",
            last_seen="",
            notebook_id="nb-3",
            notebook_source_id="old-src",
        )
    )
    provider.remove_source("old-src")
    assert android.calls[-1] == "delete_source nb-3 old-src"


def test_unknown_source_is_refused(provider):
    with pytest.raises(KnowledgeError, match="which notebook"):
        provider.source_fulltext("mystery")


def test_generate_quiz_returns_parsed_json_and_cleans_up(provider, tmp_path):
    quiz = provider.generate_quiz("nb-1", {"difficulty": "hard"})
    assert quiz == {"questions": [{"question": "Q?"}]}
    assert list((tmp_path / "out").iterdir()) == []


def test_generate_rejects_unknown_kind(provider):
    with pytest.raises(KnowledgeError, match="Unknown artifact kind"):
        provider.generate("nb-1", "hologram", {})


def test_health_reports_state_without_raising(provider, android, web):
    assert provider.health() is ProviderState.AVAILABLE
    android.fail_with = web.fail_with = RPCError("down")
    assert provider.health() is ProviderState.BROKEN


# -- LibraryTransport against a mocked notebooklm-py client -------------------------------------


class AudioFormat(enum.IntEnum):
    DEEP_DIVE = 1
    BRIEF = 2


class AudioLength(enum.IntEnum):
    SHORT = 1
    DEFAULT = 2


class Recorder:
    def __init__(self):
        self.calls = []


def fake_client(recorder: Recorder, status_kwargs=None, latest_conversation="conv-old"):
    status = SimpleNamespace(
        task_id="task-1",
        status="completed",
        error=None,
        is_rate_limited=False,
        is_failed=False,
        is_complete=True,
    )
    for k, v in (status_kwargs or {}).items():
        setattr(status, k, v)

    def rec(name, result=None):
        async def fn(*args, **kwargs):
            recorder.calls.append((name, args, kwargs))
            return result(*args, **kwargs) if callable(result) else result

        return fn

    def write_audio(nb, out):
        Path(out).write_bytes(b"\x00\x00\x00 ftypM4A ")
        return out

    return SimpleNamespace(
        notebooks=SimpleNamespace(
            list=rec("notebooks.list", [SimpleNamespace(id="nb-1", title="BrightLearn/CSE220")]),
            create=rec("notebooks.create", SimpleNamespace(id="nb-new")),
        ),
        sources=SimpleNamespace(
            add_file=rec("sources.add_file", SimpleNamespace(id="src-1")),
            delete=rec("sources.delete"),
            list=rec(
                "sources.list",
                [
                    SimpleNamespace(
                        id="src-1",
                        title="lec1.pdf",
                        kind=SimpleNamespace(value="pdf"),
                        created_at=datetime(2026, 9, 23, 12, 0),
                    )
                ],
            ),
            get_fulltext=rec("sources.get_fulltext", SimpleNamespace(content="text")),
        ),
        chat=SimpleNamespace(
            ask=rec(
                "chat.ask",
                lambda nb, q, source_ids=None, conversation_id=None: SimpleNamespace(
                    answer="Exams are 60% [1].",
                    references=[SimpleNamespace(source_id="src-1", cited_text="Exams: 60%")],
                    conversation_id=conversation_id or "conv-9",
                ),
            ),
            get_conversation_id=rec("chat.get_conversation_id", latest_conversation),
            delete_conversation=rec("chat.delete_conversation"),
        ),
        artifacts=SimpleNamespace(
            generate_audio=rec("artifacts.generate_audio", status),
            wait_for_completion=rec("artifacts.wait_for_completion", status),
            download_audio=rec("artifacts.download_audio", write_audio),
        ),
    )


class Ctx:
    def __init__(self, client):
        self.client = client
        self.entered = self.exited = 0

    async def __aenter__(self):
        self.entered += 1
        return self.client

    async def __aexit__(self, *exc):
        self.exited += 1


@pytest.fixture
def lib(monkeypatch):
    fake = SimpleNamespace(AudioFormat=AudioFormat, AudioLength=AudioLength)
    monkeypatch.setattr(gn, "_lib", lambda: fake)
    return fake


def library_provider(conn, tmp_path, client):
    ctx = Ctx(client)
    transport = gn.AndroidTransport(None, open_client=lambda: ctx)
    provider = GeminiNotebookProvider(conn, [transport], tmp_path / "out", min_interval_s=0)
    return provider, ctx


def test_library_transport_maps_sources_answers_and_notebooks(conn, tmp_path, lib):
    recorder = Recorder()
    provider, ctx = library_provider(conn, tmp_path, fake_client(recorder))

    assert provider.ensure_notebook("CSE220") == "nb-1"
    assert provider.add_file("nb-1", tmp_path / "lec1.pdf") == "src-1"
    assert provider.list_sources("nb-1") == [
        SourceMeta("src-1", "lec1.pdf", "pdf", "2026-09-23T12:00:00")
    ]
    answer = provider.query("nb-1", "Grading?", source_ids=["src-1"])
    assert answer.text == "Exams are 60% [1]."
    assert answer.citations[0].source_id == "src-1"
    assert answer.citations[0].excerpt == "Exams: 60%"
    assert provider.source_fulltext("src-1") == "text"
    provider.remove_source("src-1")

    names = [c[0] for c in recorder.calls]
    assert "notebooks.create" not in names  # found by title
    add = next(c for c in recorder.calls if c[0] == "sources.add_file")
    assert add[2] == {"wait": True}
    ask = next(c for c in recorder.calls if c[0] == "chat.ask")
    assert ask[2] == {"source_ids": ["src-1"], "conversation_id": None}
    assert ("chat.delete_conversation", ("nb-1", "conv-old"), {}) in recorder.calls
    assert ("sources.delete", ("nb-1", "src-1"), {}) in recorder.calls
    assert ctx.entered == 1  # one client for every call

    provider.close()
    assert ctx.exited == 1


def test_library_transport_creates_missing_notebook(conn, tmp_path, lib):
    recorder = Recorder()
    provider, _ = library_provider(conn, tmp_path, fake_client(recorder))
    assert provider.ensure_notebook("AMS161") == "nb-new"
    assert ("notebooks.create", ("BrightLearn/AMS161",), {}) in recorder.calls


def test_library_transport_audio_generation_waits_and_downloads(conn, tmp_path, lib):
    recorder = Recorder()
    provider, _ = library_provider(conn, tmp_path, fake_client(recorder))

    path = provider.generate_audio("nb-1", "# Focus on exams", "brief", "short")

    assert path.suffix == ".m4a" and path.exists()
    gen = next(c for c in recorder.calls if c[0] == "artifacts.generate_audio")
    assert gen[2]["audio_format"] is AudioFormat.BRIEF
    assert gen[2]["audio_length"] is AudioLength.SHORT
    assert gen[2]["instructions"] == "# Focus on exams"
    wait = next(c for c in recorder.calls if c[0] == "artifacts.wait_for_completion")
    assert wait[1] == ("nb-1", "task-1")


def test_library_transport_rate_limited_generation(conn, tmp_path, lib):
    recorder = Recorder()
    client = fake_client(recorder, {"is_rate_limited": True, "error": "quota"})
    provider, _ = library_provider(conn, tmp_path, client)

    with pytest.raises(KnowledgeRateLimited):
        provider.generate_audio("nb-1", "", "brief", "short")
    assert provider.state is ProviderState.RATE_LIMITED


def test_library_transport_rejects_unknown_enum_value(conn, tmp_path, lib):
    provider, _ = library_provider(conn, tmp_path, fake_client(Recorder()))
    with pytest.raises(KnowledgeError, match="deep_dive, brief"):
        provider.generate_audio("nb-1", "", "podcast", "short")
    assert provider.state is ProviderState.AVAILABLE


def test_failed_generation_does_not_fall_back(conn, tmp_path, lib):
    recorder = Recorder()
    client = fake_client(recorder, {"is_failed": True, "error": "policy"})
    web = FakeTransport("web")
    ctx = Ctx(client)
    provider = GeminiNotebookProvider(
        conn, [gn.AndroidTransport(None, open_client=lambda: ctx), web], tmp_path, min_interval_s=0
    )
    with pytest.raises(KnowledgeError, match="policy"):
        provider.generate_audio("nb-1", "", "brief", "short")
    assert web.calls == []
    assert provider.state is ProviderState.AVAILABLE


def test_missing_library_is_a_knowledge_error(conn, tmp_path, monkeypatch):
    def missing(name):
        raise ImportError(name)

    monkeypatch.setattr(gn.importlib, "import_module", missing)
    provider = GeminiNotebookProvider(
        conn, [gn.AndroidTransport(None), gn.WebTransport(None)], tmp_path, min_interval_s=0
    )
    with pytest.raises(KnowledgeError, match="not installed"):
        provider.list_sources("nb-1")
    assert provider.state is ProviderState.BROKEN


def test_query_without_a_handle_starts_a_fresh_conversation_every_time(conn, tmp_path, lib):
    recorder = Recorder()
    provider, _ = library_provider(conn, tmp_path, fake_client(recorder))

    provider.query("nb-1", "q1")
    provider.query("nb-1", "q2")

    names = [c[0] for c in recorder.calls]
    assert names.count("chat.delete_conversation") == 2
    asks = [c for c in recorder.calls if c[0] == "chat.ask"]
    assert all(c[2]["conversation_id"] is None for c in asks)


def test_a_conversation_handle_is_fresh_once_then_follows_up(conn, tmp_path, lib):
    recorder = Recorder()
    provider, _ = library_provider(conn, tmp_path, fake_client(recorder))
    session = Conversation()

    first = provider.query("nb-1", "What is a pointer?", conversation=session)
    provider.query("nb-1", "Why?", conversation=session)

    assert session.conversation_id == "conv-9" == first.conversation_id
    asks = [c for c in recorder.calls if c[0] == "chat.ask"]
    assert [c[2]["conversation_id"] for c in asks] == [None, "conv-9"]
    assert [c[0] for c in recorder.calls].count("chat.delete_conversation") == 1


def test_fresh_query_on_a_notebook_without_history_deletes_nothing(conn, tmp_path, lib):
    recorder = Recorder()
    provider, _ = library_provider(conn, tmp_path, fake_client(recorder, latest_conversation=None))
    provider.query("nb-1", "q")
    assert "chat.delete_conversation" not in [c[0] for c in recorder.calls]


def test_from_config_points_notebooklm_home_at_brightlearn(config, monkeypatch):
    monkeypatch.delenv("NOTEBOOKLM_HOME", raising=False)
    provider = GeminiNotebookProvider.from_config(config, connect(":memory:"))
    try:
        assert gn.os.environ["NOTEBOOKLM_HOME"] == str(config.home / "notebooklm")
    finally:
        provider.close()
        monkeypatch.delenv("NOTEBOOKLM_HOME", raising=False)


def test_auth_check_without_a_login_explains_where_to_log_in(config, monkeypatch, tmp_path):
    monkeypatch.setattr(gn.Path, "home", lambda: tmp_path / "nohome")
    ok, detail = gn.auth_check(config)
    assert not ok and "brightlearn dev nlm-login" in detail

    stray = tmp_path / "nohome/.notebooklm/profiles/default/storage_state.json"
    stray.parent.mkdir(parents=True)
    stray.write_text("{}")
    ok, detail = gn.auth_check(config)
    assert not ok and "~/.notebooklm" in detail


def test_login_runs_the_library_cli_with_brightlearn_home(config, monkeypatch):
    seen = {}

    def fake_run(cmd, env):
        seen.update(cmd=cmd, home=env["NOTEBOOKLM_HOME"])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(gn.subprocess, "run", fake_run)
    assert gn.login(config, "me@example.com") == 0
    assert seen["cmd"][-4:] == ["login", "--master-token", "--account", "me@example.com"]
    assert seen["home"] == str(config.home / "notebooklm")
