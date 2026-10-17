"""The health checks behind ``brightlearn doctor``, kept out of ``cli/`` so the API runs the same.

Doctor must be safe to run any time, so no check changes anything or spends subscription quota:
each reads local state or runs a free probe (``--version``, NotebookLM's auth check, Ollama's
local tag list). A check that crashes is reported as failed instead of hiding the ones after it.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from core import wiring
from core.config import Config
from core.memory.schema import SCHEMA_VERSION
from core.providers.knowledge import gemini_notebook
from core.providers.models.cli_base import CLIModelProvider
from core.providers.models.ollama import OllamaProvider
from core.providers.state import ProviderState
from core.providers.storage.local import LocalStorageBackend

log = logging.getLogger(__name__)


class Status(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    OFF = "not configured"


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str


def check_config(config: Config) -> Check:
    detail = f"home {config.home}, term {config.term}"
    if config.home.exists() and stat.S_IMODE(config.home.stat().st_mode) & 0o077:
        return Check("Config", Status.WARN, f"{detail}; {config.home} is readable by others")
    return Check("Config", Status.OK, detail)


def check_db(config: Config) -> Check:
    if not config.db_path.exists():
        return Check(
            "DB schema", Status.WARN, "no database yet; `brightlearn courses add` creates it"
        )
    conn = sqlite3.connect(f"file:{config.db_path}?mode=ro", uri=True)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    if version == SCHEMA_VERSION:
        return Check("DB schema", Status.OK, f"v{version}")
    if version < SCHEMA_VERSION:
        return Check(
            "DB schema", Status.WARN, f"v{version}; migrates to v{SCHEMA_VERSION} on next run"
        )
    return Check(
        "DB schema", Status.FAIL, f"v{version} is newer than this code (v{SCHEMA_VERSION})"
    )


def check_storage(config: Config) -> Check:
    state = LocalStorageBackend(config.storage_root).health()
    if state is ProviderState.AVAILABLE:
        return Check("Storage root", Status.OK, f"{config.storage_root} writable")
    return Check("Storage root", Status.FAIL, f"{config.storage_root} not writable")


def check_tmp(config: Config) -> Check:
    """Upload staging is emptied after every import, so a leftover means one crashed."""
    leftovers = list(config.tmp_dir.iterdir()) if config.tmp_dir.is_dir() else []
    if leftovers:
        return Check(
            "Temp dir", Status.FAIL, f"{len(leftovers)} leftover file(s) in {config.tmp_dir}"
        )
    return Check("Temp dir", Status.OK, f"{config.tmp_dir} empty")


def check_api_key(env: Mapping[str, str]) -> Check:
    if env.get("ANTHROPIC_API_KEY"):
        return Check("ANTHROPIC_API_KEY", Status.FAIL, "set: Claude Code would bill the API")
    return Check("ANTHROPIC_API_KEY", Status.OK, "unset")


def check_notebooklm(config: Config) -> Check:
    if not gemini_notebook.library_installed():
        return Check("NotebookLM", Status.WARN, f"not installed: {gemini_notebook.INSTALL_HINT}")
    ok, detail = gemini_notebook.auth_check(config)
    return Check("NotebookLM", Status.OK if ok else Status.FAIL, detail)


def check_model_cli(name: str, provider: CLIModelProvider) -> Check:
    """``<binary> --version`` only: an auth check would spend subscription quota."""
    version = provider.version()
    if version is None:
        return Check(name, Status.WARN, f"`{provider.binary}` not on PATH")
    return Check(name, Status.OK, f"{version}; login not checked")


def check_ollama(provider: OllamaProvider) -> Check:
    """``GET /api/tags`` on the local server: free, and optional (housekeeping only)."""
    state = provider.health()
    if state is ProviderState.AVAILABLE:
        return Check("Ollama", Status.OK, f"{provider.model} at {provider.base_url}")
    return Check("Ollama", Status.WARN, f"{provider.detail or state}; optional (housekeeping only)")


def not_configured(name: str, ticket: str) -> Check:
    return Check(name, Status.OFF, f"arrives in {ticket}")


def checks(config: Config) -> list[tuple[str, Callable[[], Check]]]:
    return [
        ("Config", lambda: check_config(config)),
        ("DB schema", lambda: check_db(config)),
        ("Storage root", lambda: check_storage(config)),
        ("Temp dir", lambda: check_tmp(config)),
        ("ANTHROPIC_API_KEY", lambda: check_api_key(os.environ)),
        ("NotebookLM", lambda: check_notebooklm(config)),
        (
            "Claude Code",
            lambda: check_model_cli("Claude Code", wiring.open_model("claude", config)),
        ),
        ("Codex", lambda: check_model_cli("Codex", wiring.open_model("codex", config))),
        ("Ollama", lambda: check_ollama(wiring.open_model("ollama", config))),
    ]


def run_checks(config: Config) -> list[Check]:
    results: list[Check] = []
    for name, check in checks(config):
        try:
            results.append(check())
        except Exception as exc:
            log.debug("doctor check %s failed", name, exc_info=True)
            results.append(Check(name, Status.FAIL, f"{type(exc).__name__}: {exc}"))
    return results
