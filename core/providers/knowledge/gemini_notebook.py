"""NotebookLM (Gemini Notebook) over notebooklm-py, Android transport first, web as fallback.

notebooklm-py is async only; the provider owns one event loop and runs every call on it, so the
library's clients (which are bound to their loop) stay usable across calls. The library is
imported lazily: this module imports cleanly without it, and tests replace the transports.

Fallback policy per call:
- Android succeeds -> AVAILABLE.
- Android fails, web succeeds -> LIMITED.
- Both fail -> BROKEN (AUTH_EXPIRED when every failure was an auth failure).
- A rate limit on any transport -> RATE_LIMITED, no fallback (the quota is per account).
- Caller errors (not found, validation) are raised straight away; the state is unchanged.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol, TypeVar

from core.config import Config
from core.ledger.ledger import Ledger, ModelRun, estimate_tokens, utcnow
from core.providers.knowledge.base import (
    Citation,
    Conversation,
    GroundedAnswer,
    KnowledgeError,
    KnowledgeProvider,
    KnowledgeRateLimited,
    ProviderState,
    SourceMeta,
    notebook_title,
)

log = logging.getLogger(__name__)

T = TypeVar("T")

PROVIDER = "notebooklm"
INSTALL_HINT = "re-run ./setup.sh (setup.cmd on Windows), which installs it"

# Artifact kinds -> download file extension.
ARTIFACT_EXT = {
    "audio": ".m4a",
    "quiz": ".json",
    "flashcards": ".json",
    "report": ".md",
    "slides": ".pdf",
    "mind_map": ".json",
}

_RATE_LIMIT_ERRORS = {"RateLimitError", "KnowledgeRateLimited"}
# Errors about the request or the artifact, not the transport: no fallback, state unchanged.
_CALLER_ERRORS = {"ValidationError", "NotFoundError", "InvalidRequest", "ArtifactFailed"}
_AUTH_ERRORS = {"AuthError", "ConfigurationError", "MasterTokenError"}


class InvalidRequest(KnowledgeError):
    pass


class ArtifactFailed(KnowledgeError):
    """NotebookLM finished the generation without producing an artifact."""


def _names(exc: BaseException) -> set[str]:
    return {cls.__name__ for cls in type(exc).__mro__}


def _lib() -> Any:
    try:
        return importlib.import_module("notebooklm")
    except ImportError as exc:
        raise KnowledgeError(f"notebooklm-py is not installed: {INSTALL_HINT}") from exc


def _enum(enum_cls: Any, value: str | None) -> Any:
    if value is None:
        return None
    try:
        return enum_cls[value.strip().upper().replace("-", "_").replace(" ", "_")]
    except KeyError as exc:
        choices = ", ".join(m.name.lower() for m in enum_cls)
        raise InvalidRequest(f"{value!r} is not one of: {choices}") from exc


class Transport(Protocol):
    name: str

    async def find_or_create_notebook(self, title: str) -> str: ...
    async def list_notebooks(self) -> list[tuple[str, str]]: ...
    async def add_file(self, notebook_id: str, path: Path) -> str: ...
    async def delete_source(self, notebook_id: str, source_id: str) -> None: ...
    async def list_sources(self, notebook_id: str) -> list[SourceMeta]: ...
    async def refresh_source(self, notebook_id: str, source_id: str) -> None: ...
    async def ask(
        self,
        notebook_id: str,
        question: str,
        source_ids: list[str] | None,
        conversation_id: str | None,
    ) -> GroundedAnswer:
        """``conversation_id=None`` starts a fresh conversation."""

    async def fulltext(self, notebook_id: str, source_id: str) -> str: ...
    async def generate(
        self, notebook_id: str, kind: str, options: dict[str, Any], dest: Path, timeout_s: float
    ) -> Path: ...
    async def close(self) -> None: ...


class LibraryTransport:
    """One notebooklm-py client on one backend, opened lazily."""

    name = "web"

    def __init__(
        self,
        storage_path: Path | None,
        open_client: Callable[[], Any] | None = None,
    ) -> None:
        self._storage_path = storage_path
        self._open_client = open_client or self._default_open
        self._ctx: Any = None
        self._client: Any = None

    def _default_open(self) -> Any:
        path = str(self._storage_path) if self._storage_path else None
        return _lib().NotebookLMClient.from_storage(path, backend=self.name)

    async def _c(self) -> Any:
        if self._client is None:
            ctx = self._open_client()
            self._client = await ctx.__aenter__()
            self._ctx = ctx
        return self._client

    async def close(self) -> None:
        if self._ctx is not None:
            ctx, self._ctx, self._client = self._ctx, None, None
            await ctx.__aexit__(None, None, None)

    async def list_notebooks(self) -> list[tuple[str, str]]:
        return [(nb.id, nb.title) for nb in await (await self._c()).notebooks.list()]

    async def find_or_create_notebook(self, title: str) -> str:
        for notebook_id, existing in await self.list_notebooks():
            if existing == title:
                return notebook_id
        return (await (await self._c()).notebooks.create(title)).id

    async def add_file(self, notebook_id: str, path: Path) -> str:
        source = await (await self._c()).sources.add_file(notebook_id, path, wait=True)
        return source.id

    async def delete_source(self, notebook_id: str, source_id: str) -> None:
        await (await self._c()).sources.delete(notebook_id, source_id)

    async def list_sources(self, notebook_id: str) -> list[SourceMeta]:
        sources = await (await self._c()).sources.list(notebook_id)
        return [
            SourceMeta(
                source_id=s.id,
                title=s.title or "",
                kind=str(getattr(s.kind, "value", s.kind)),
                added_at=s.created_at.isoformat() if s.created_at else None,
            )
            for s in sources
        ]

    async def refresh_source(self, notebook_id: str, source_id: str) -> None:
        await (await self._c()).sources.refresh(notebook_id, source_id)

    async def ask(
        self,
        notebook_id: str,
        question: str,
        source_ids: list[str] | None,
        conversation_id: str | None,
    ) -> GroundedAnswer:
        chat = (await self._c()).chat
        if conversation_id is None:
            # chat.ask without a conversation id extends the notebook's latest conversation; the
            # library's documented way to force a new one is to delete that conversation first.
            latest = await chat.get_conversation_id(notebook_id)
            if latest:
                await chat.delete_conversation(notebook_id, latest)
        result = await chat.ask(
            notebook_id, question, source_ids=source_ids, conversation_id=conversation_id
        )
        citations = [Citation(r.source_id, r.cited_text or "") for r in result.references]
        return GroundedAnswer(result.answer, citations, result.conversation_id)

    async def fulltext(self, notebook_id: str, source_id: str) -> str:
        return (await (await self._c()).sources.get_fulltext(notebook_id, source_id)).content

    async def generate(
        self, notebook_id: str, kind: str, options: dict[str, Any], dest: Path, timeout_s: float
    ) -> Path:
        lib, artifacts = _lib(), (await self._c()).artifacts
        instructions = options.get("instructions")
        source_ids = options.get("source_ids")
        if kind == "mind_map":
            result = await artifacts.generate_mind_map(
                notebook_id, source_ids=source_ids, instructions=instructions
            )
            dest.write_text(json.dumps(result.mind_map, indent=2), encoding="utf-8")
            return dest

        if kind == "audio":
            start = artifacts.generate_audio(
                notebook_id,
                source_ids=source_ids,
                language=options.get("language", "en"),
                instructions=instructions,
                audio_format=_enum(lib.AudioFormat, options.get("format")),
                audio_length=_enum(lib.AudioLength, options.get("length")),
            )
            download = artifacts.download_audio
        elif kind in ("quiz", "flashcards"):
            generate = artifacts.generate_quiz if kind == "quiz" else artifacts.generate_flashcards
            start = generate(
                notebook_id,
                source_ids=source_ids,
                instructions=instructions,
                quantity=_enum(lib.QuizQuantity, options.get("quantity")),
                difficulty=_enum(lib.QuizDifficulty, options.get("difficulty")),
            )
            fetch = artifacts.download_quiz if kind == "quiz" else artifacts.download_flashcards

            async def download(nb: str, out: str) -> str:
                return await fetch(nb, out, output_format="json")

        elif kind == "report":
            report_format = _enum(lib.ReportFormat, options.get("format")) or (
                lib.ReportFormat.CUSTOM if options.get("prompt") else lib.ReportFormat.BRIEFING_DOC
            )
            start = artifacts.generate_report(
                notebook_id,
                report_format=report_format,
                source_ids=source_ids,
                language=options.get("language", "en"),
                custom_prompt=options.get("prompt"),
                extra_instructions=instructions,
            )
            download = artifacts.download_report
        elif kind == "slides":
            start = artifacts.generate_slide_deck(
                notebook_id,
                source_ids=source_ids,
                language=options.get("language", "en"),
                instructions=instructions,
                slide_format=_enum(lib.SlideDeckFormat, options.get("format")),
                slide_length=_enum(lib.SlideDeckLength, options.get("length")),
            )

            async def download(nb: str, out: str) -> str:
                return await artifacts.download_slide_deck(nb, out, output_format="pdf")

        else:
            raise InvalidRequest(f"Unknown artifact kind {kind!r}")

        status = await start
        if status.is_rate_limited:
            raise KnowledgeRateLimited(f"{kind} generation rejected: {status.error}")
        if status.is_failed:
            raise ArtifactFailed(f"{kind} generation failed: {status.error}")
        done = await artifacts.wait_for_completion(notebook_id, status.task_id, timeout=timeout_s)
        if done.is_rate_limited:
            raise KnowledgeRateLimited(f"{kind} generation rejected: {done.error}")
        if not done.is_complete:
            raise ArtifactFailed(f"{kind} generation ended {done.status}: {done.error}")
        # artifact_id=None downloads the latest completed artifact of this kind.
        return Path(await download(notebook_id, str(dest)))


class AndroidTransport(LibraryTransport):
    name = "android"


class WebTransport(LibraryTransport):
    name = "web"


class GeminiNotebookProvider(KnowledgeProvider):
    def __init__(
        self,
        conn: sqlite3.Connection,
        transports: list[Transport],
        out_dir: Path,
        min_interval_s: float = 1.5,
        artifact_timeout_s: float = 1200.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._conn = conn
        self._ledger = Ledger(conn)
        self._transports = transports
        self._out_dir = out_dir
        self._min_interval_s = min_interval_s
        self._artifact_timeout_s = artifact_timeout_s
        self._clock = clock
        self._sleep = sleep
        self._last_call: float | None = None
        self._loop = asyncio.new_event_loop()
        self._source_notebooks: dict[str, str] = {}
        self.state = ProviderState.AVAILABLE

    @classmethod
    def from_config(cls, config: Config, conn: sqlite3.Connection) -> GeminiNotebookProvider:
        use_brightlearn_home(config)
        storage = config.notebooklm_storage_path
        return cls(
            conn,
            [AndroidTransport(storage), WebTransport(storage)],
            out_dir=config.notebooklm_home / "downloads",
            min_interval_s=config.nlm_min_interval_s,
            artifact_timeout_s=config.nlm_artifact_timeout_s,
        )

    def close(self) -> None:
        for transport in self._transports:
            try:
                self._loop.run_until_complete(transport.close())
            except Exception:
                log.debug("Closing %s transport failed", transport.name, exc_info=True)
        self._loop.close()

    # -- KnowledgeProvider -------------------------------------------------------------------

    def ensure_notebook(self, course: str) -> str:
        row = self._conn.execute(
            "SELECT notebook_id FROM notebooks WHERE course = ?", (course,)
        ).fetchone()
        if row:
            return row[0]
        notebook_id = self.notebook_by_title(notebook_title(course), task_type="ensure_notebook")
        with self._conn:
            self._conn.execute(
                "INSERT INTO notebooks (course, notebook_id, created_at) VALUES (?, ?, ?)",
                (course, notebook_id, utcnow()),
            )
        return notebook_id

    def notebook_by_title(self, title: str, task_type: str = "notebook_by_title") -> str:
        """Find a notebook by exact title, creating it if missing. Not cached."""
        return self._call(task_type, lambda t: t.find_or_create_notebook(title))

    def add_file(self, notebook_id: str, path: Path) -> str:
        source_id = self._call("add_file", lambda t: t.add_file(notebook_id, path))
        self._source_notebooks[source_id] = notebook_id
        return source_id

    def remove_source(self, source_id: str) -> None:
        notebook_id = self._notebook_of(source_id)
        self._call("remove_source", lambda t: t.delete_source(notebook_id, source_id))
        self._source_notebooks.pop(source_id, None)

    def list_sources(self, notebook_id: str) -> list[SourceMeta]:
        sources = self._call("list_sources", lambda t: t.list_sources(notebook_id))
        self._source_notebooks.update({s.source_id: notebook_id for s in sources})
        return sources

    def refresh_source(self, source_id: str) -> None:
        notebook_id = self._notebook_of(source_id)
        self._call("refresh_source", lambda t: t.refresh_source(notebook_id, source_id))

    def query(
        self,
        notebook_id: str,
        question: str,
        source_ids: list[str] | None = None,
        conversation: Conversation | None = None,
    ) -> GroundedAnswer:
        conversation_id = conversation.conversation_id if conversation else None
        answer = self._call(
            "query",
            lambda t: t.ask(notebook_id, question, source_ids, conversation_id),
            input_text=question,
            output_text=lambda answer: answer.text,
        )
        if conversation is not None and conversation.conversation_id is None:
            conversation.conversation_id = answer.conversation_id
        return answer

    def source_fulltext(self, source_id: str) -> str:
        notebook_id = self._notebook_of(source_id)
        return self._call("source_fulltext", lambda t: t.fulltext(notebook_id, source_id))

    def generate_quiz(self, notebook_id: str, spec: dict[str, Any] | None = None) -> dict:
        path = self._generate("generate_quiz", notebook_id, "quiz", dict(spec or {}))
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        finally:
            path.unlink(missing_ok=True)

    def generate_audio(
        self, notebook_id: str, instructions_md: str, format: str, length: str
    ) -> Path:
        options = {"instructions": instructions_md, "format": format, "length": length}
        return self._generate("generate_audio", notebook_id, "audio", options)

    def generate(self, notebook_id: str, kind: str, options: dict[str, Any]) -> Path:
        return self._generate("generate", notebook_id, kind, options)

    def health(self) -> ProviderState:
        """Cheap synthetic check: list notebooks. Never generates anything."""
        try:
            self._call("health", lambda t: t.list_notebooks())
        except KnowledgeError:
            pass
        return self.state

    # -- internals ---------------------------------------------------------------------------

    def _generate(self, task_type: str, notebook_id: str, kind: str, options: dict) -> Path:
        if kind not in ARTIFACT_EXT:
            raise InvalidRequest(f"Unknown artifact kind {kind!r}; one of {sorted(ARTIFACT_EXT)}")
        self._out_dir.mkdir(parents=True, exist_ok=True)
        dest = self._out_dir / f"{uuid.uuid4().hex}{ARTIFACT_EXT[kind]}"
        timeout = self._artifact_timeout_s
        return self._call(
            task_type, lambda t: t.generate(notebook_id, kind, options, dest, timeout)
        )

    def _notebook_of(self, source_id: str) -> str:
        if source_id in self._source_notebooks:
            return self._source_notebooks[source_id]
        row = self._conn.execute(
            "SELECT notebook_id FROM resources WHERE notebook_source_id = ?", (source_id,)
        ).fetchone()
        if row and row[0]:
            return row[0]
        raise KnowledgeError(f"Don't know which notebook holds source {source_id}")

    def _pace(self) -> None:
        if self._last_call is not None:
            wait = self._last_call + self._min_interval_s - self._clock()
            if wait > 0:
                self._sleep(wait)

    def _call(
        self,
        task_type: str,
        op: Callable[[Transport], Awaitable[T]],
        input_text: str | None = None,
        output_text: Callable[[T], str] | None = None,
    ) -> T:
        started_at, t0 = utcnow(), time.monotonic()
        failures: list[tuple[str, BaseException]] = []
        for transport in self._transports:
            self._pace()
            try:
                result = self._loop.run_until_complete(op(transport))
            except Exception as exc:
                names = _names(exc)
                failures.append((transport.name, exc))
                if names & _RATE_LIMIT_ERRORS:
                    self.state = ProviderState.RATE_LIMITED
                    break
                if names & _CALLER_ERRORS:
                    break
                log.warning("NotebookLM %s failed on %s: %s", task_type, transport.name, exc)
                continue
            finally:
                self._last_call = self._clock()
            fell_back = transport is not self._transports[0]
            self.state = ProviderState.LIMITED if fell_back else ProviderState.AVAILABLE
            self._record(
                task_type,
                started_at,
                t0,
                True,
                model=transport.name,
                fallback_from=self._transports[0].name if fell_back else None,
                input_text=input_text,
                output_text=output_text(result) if output_text else None,
            )
            return result

        name, exc = failures[-1]
        names = _names(exc)
        if not (names & (_RATE_LIMIT_ERRORS | _CALLER_ERRORS)):
            if all(_names(e) & _AUTH_ERRORS for _, e in failures):
                self.state = ProviderState.AUTH_EXPIRED
            else:
                self.state = ProviderState.BROKEN
        self._record(
            task_type,
            started_at,
            t0,
            False,
            model=name,
            error=f"{type(exc).__name__}: {exc}",
            input_text=input_text,
        )
        error_cls = KnowledgeRateLimited if names & _RATE_LIMIT_ERRORS else KnowledgeError
        raise error_cls(f"NotebookLM {task_type} failed on {name}: {exc}") from exc

    def _record(
        self,
        task_type: str,
        started_at: str,
        t0: float,
        success: bool,
        model: str | None,
        fallback_from: str | None = None,
        error: str | None = None,
        input_text: str | None = None,
        output_text: str | None = None,
    ) -> None:
        self._ledger.record(
            ModelRun(
                provider=PROVIDER,
                model=model,
                task_type=task_type,
                started_at=started_at,
                duration_ms=int((time.monotonic() - t0) * 1000),
                success=success,
                input_tokens_est=estimate_tokens(input_text) if input_text else None,
                output_tokens_est=estimate_tokens(output_text) if output_text else None,
                fallback_from=fallback_from,
                error=error,
            )
        )


def use_brightlearn_home(config: Config) -> None:
    """Point notebooklm-py at ``~/.brightlearn/notebooklm`` for this process (P20), so its
    master token and cookies live with BrightLearn's other secrets."""
    os.environ["NOTEBOOKLM_HOME"] = str(config.notebooklm_home)


def notebooklm_env(config: Config) -> dict[str, str]:
    return {**os.environ, "NOTEBOOKLM_HOME": str(config.notebooklm_home)}


def default_library_storage() -> Path:
    """Where ``notebooklm login`` writes when NOTEBOOKLM_HOME is unset."""
    return Path.home() / ".notebooklm" / "profiles" / "default" / "storage_state.json"


def library_installed() -> bool:
    return importlib.util.find_spec("notebooklm") is not None


def login(config: Config, account: str, browser: str | None = None) -> int:
    """``notebooklm login --master-token --account <account>`` into BrightLearn's profile.
    Interactive: the library opens a browser. ``browser`` picks an installed one (``chrome``,
    ``msedge``): Playwright's bundled Chromium isn't downloaded by the install, and the library
    says it crashes on macOS 15+ anyway. Returns the exit code."""
    config.notebooklm_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "notebooklm", "login", "--master-token", "--account", account]
    if browser:
        cmd += ["--browser", browser]
    return subprocess.run(cmd, env=notebooklm_env(config)).returncode


def auth_check(config: Config, timeout_s: float = 60.0) -> tuple[bool, str]:
    """``notebooklm auth check --json`` against BrightLearn's NotebookLM profile."""
    if not config.notebooklm_storage_path.exists():
        where = config.notebooklm_home
        if default_library_storage().exists():
            return False, (
                f"no login in {where}, but one exists in ~/.notebooklm (made without "
                "NOTEBOOKLM_HOME); run `brightlearn setup`"
            )
        return False, f"no login in {where}; run `brightlearn setup`"
    cmd = [
        sys.executable,
        "-m",
        "notebooklm",
        "--storage",
        str(config.notebooklm_storage_path),
        "auth",
        "check",
        "--json",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            env=notebooklm_env(config),
        )
    except subprocess.TimeoutExpired:
        return False, f"`notebooklm auth check` timed out after {timeout_s:.0f}s"
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        payload = {}
    ok = proc.returncode == 0 and payload.get("status", "ok") == "ok"
    if ok:
        return True, f"auth check ok ({payload.get('account') or 'account unknown'})"
    detail = payload.get("details") or proc.stderr.strip() or proc.stdout.strip()
    return False, f"auth check failed: {str(detail)[:200]}"
