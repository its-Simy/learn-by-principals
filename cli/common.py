"""Provider factories shared by the CLI commands. Tests replace these with fakes."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from core.config import Config
from core.providers.knowledge.gemini_notebook import GeminiNotebookProvider
from core.providers.lms.base import LMSProvider
from core.providers.lms.brightspace import BrightspaceSessionProvider
from core.providers.lms.session import PlaywrightSession


@contextmanager
def open_lms(config: Config) -> Iterator[LMSProvider]:
    session = PlaywrightSession(
        config.brightspace_base_url,
        config.browser_profile_dir,
        config.storage_state_path,
        config.login_timeout_s,
    )
    try:
        yield BrightspaceSessionProvider(session)
    finally:
        session.close()


@contextmanager
def open_knowledge(config: Config, conn: sqlite3.Connection) -> Iterator[GeminiNotebookProvider]:
    provider = GeminiNotebookProvider.from_config(config, conn)
    try:
        yield provider
    finally:
        provider.close()
