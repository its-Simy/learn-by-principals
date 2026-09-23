"""Provider factories shared by the CLI commands. Tests replace these with fakes."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from core.analysis.analyzer import AnalysisError, Analyzer
from core.analysis.challenge import ChallengeRunner, ChallengeStore, queue_challenges
from core.config import Config
from core.context.compiler import ContextCompiler
from core.ledger.ledger import Ledger
from core.memory.learner import LearnerMemory
from core.memory.vault import Vault
from core.providers.knowledge.gemini_notebook import GeminiNotebookProvider
from core.providers.lms.base import LMSProvider
from core.providers.lms.brightspace import BrightspaceSessionProvider
from core.providers.lms.session import PlaywrightSession
from core.providers.models.base import ModelProvider
from core.providers.models.claude_code import ClaudeCodeProvider
from core.providers.models.codex import CodexProvider
from core.providers.models.ollama import OllamaProvider
from core.router.router import Router
from core.tutor import Tutor

MODEL_PROVIDERS = {"claude": ClaudeCodeProvider, "codex": CodexProvider, "ollama": OllamaProvider}


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


def open_model(name: str, config: Config) -> ModelProvider:
    if name not in MODEL_PROVIDERS:
        raise ValueError(f"Unknown model provider {name!r}; one of {sorted(MODEL_PROVIDERS)}")
    return MODEL_PROVIDERS[name].from_config(config)


def model_providers(config: Config, purposes: tuple[str, ...]) -> dict[str, ModelProvider]:
    """One provider object per name in the routing orders for ``purposes``."""
    names = dict.fromkeys(n for p in purposes for n in config.routing[p])
    return {name: open_model(name, config) for name in names}


def router(config: Config, conn: sqlite3.Connection, providers: dict[str, ModelProvider]) -> Router:
    """Router v1: the ``[routing]`` order per task type, health and benchmarks (BL-035)."""
    return Router(providers, Ledger(conn), config.routing)


def session_end_hook(config: Config, conn: sqlite3.Connection, providers: dict[str, ModelProvider]):
    """On /end: the tutor's own estimate, then the Analyzer on a provider other than the tutor's
    (BL-027, ``[routing] analysis`` order), then a challenge for every disagreement (BL-030)."""
    analysis = router(config, conn, providers)

    def hook(tutor: Tutor) -> str | None:
        if tutor.row is None or not tutor.session or not tutor.session.turns:
            return None
        estimate = tutor.self_estimate()
        analyzer = Analyzer(analysis, LearnerMemory(conn), Vault(config.vault_root))
        try:
            report = analyzer.analyze(
                tutor.row, tutor.transcript_path.read_text(), estimate[1] if estimate else None
            )
        except AnalysisError as exc:
            return str(exc)
        queued = queue_challenges(ChallengeStore(conn), report, estimate[0] if estimate else None)
        note = f" {len(queued)} challenge(s) queued for next session." if queued else ""
        return report.summary() + note

    return hook


def challenge_runner(
    config: Config,
    conn: sqlite3.Connection,
    providers: dict[str, ModelProvider],
    compiler: ContextCompiler,
) -> ChallengeRunner:
    """The Challenger (``question_gen``) asks on the ``teaching`` order; the Analyzer grades on
    ``analysis``, off the provider that asked."""
    learner = LearnerMemory(conn)
    shared = router(config, conn, providers)
    return ChallengeRunner(
        ChallengeStore(conn), learner, shared, Analyzer(shared, learner), compiler
    )
