"""Shared plumbing for model CLIs run as subprocesses (``claude -p``, ``codex exec``).

Each call runs in a scratch directory, with ``ANTHROPIC_API_KEY`` removed from the environment
so a subscription CLI can never fall back to metered API billing (principle 1).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path

from core.providers.models.base import (
    ModelError,
    ModelProvider,
    ModelRateLimited,
    ModelResult,
    ModelTimeout,
    ProviderState,
    TaskPackage,
    UsageHint,
)

log = logging.getLogger(__name__)

SCRUBBED_ENV = ("ANTHROPIC_API_KEY",)
HEALTH_TTL_S = 600.0

RATE_LIMIT_RE = re.compile(
    r"usage limit|rate[ -]?limit|limit reached|hit your (usage )?limit|quota|too many requests"
    r"|resets? (at|in) ",
    re.IGNORECASE,
)
AUTH_RE = re.compile(
    r"not logged in|please (run )?/?login|invalid api key|authentication|unauthori[sz]ed"
    r"|oauth token",
    re.IGNORECASE,
)
RESETS_RE = re.compile(r"resets?(?: at| in)? ([^\n.|]+)", re.IGNORECASE)


class ModelAuthError(ModelError):
    pass


@dataclass(frozen=True)
class Completed:
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int


def limit_hint(text: str) -> UsageHint:
    resets = RESETS_RE.search(text)
    return UsageHint(limit_message=text.strip()[:300], resets_at=resets and resets.group(1).strip())


class CLIModelProvider(ModelProvider):
    name = "cli"
    binary = "cli"

    def __init__(
        self,
        scratch_dir: Path,
        timeout_s: float = 300.0,
        binary: str | None = None,
        clock=time.monotonic,
    ) -> None:
        self.scratch_dir = scratch_dir
        self.timeout_s = timeout_s
        self.binary = binary or self.binary
        self._clock = clock
        self.state = ProviderState.AVAILABLE
        self._last_hint: UsageHint | None = None
        self._health: tuple[float, ProviderState] | None = None

    # -- subclass hooks ----------------------------------------------------------------------

    @abstractmethod
    def argv(self, task: TaskPackage) -> list[str]: ...

    @abstractmethod
    def parse(self, done: Completed) -> tuple[str, str | None, UsageHint | None]:
        """(text, model, usage hint) from a finished process; raise ModelError on failure."""

    # -- ModelProvider -----------------------------------------------------------------------

    def run(self, task: TaskPackage) -> ModelResult:
        done = self._exec(self.argv(task))
        try:
            text, model, hint = self.parse(done)
        except ModelRateLimited as exc:
            self.state = ProviderState.RATE_LIMITED
            self._last_hint = exc.hint
            raise
        except ModelAuthError:
            self.state = ProviderState.AUTH_EXPIRED
            raise
        except ModelError:
            self.state = ProviderState.BROKEN
            raise
        self.state = ProviderState.AVAILABLE
        self._last_hint = hint
        return ModelResult(text, self.name, model, done.duration_ms, hint)

    def health(self) -> ProviderState:
        """A one-token call, cached for ten minutes."""
        now = self._clock()
        if self._health and now - self._health[0] < HEALTH_TTL_S:
            return self._health[1]
        if self.executable() is None:
            state = ProviderState.DISABLED
        else:
            try:
                self.run(TaskPackage("health", None, "", "Reply with the single word OK.", 5))
            except ModelError:
                pass
            state = self.state
        self._health = (now, state)
        return state

    def usage_hint(self) -> UsageHint | None:
        return self._last_hint

    def executable(self) -> str | None:
        return shutil.which(self.binary)

    def version(self) -> str | None:
        """``<binary> --version``, or None when the binary isn't on PATH."""
        exe = self.executable()
        if exe is None:
            return None
        proc = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=30, env=self.env()
        )
        return (proc.stdout or proc.stderr).strip() or None

    # -- internals ---------------------------------------------------------------------------

    def env(self) -> dict[str, str]:
        env = dict(os.environ)
        for key in SCRUBBED_ENV:
            env.pop(key, None)
        return env

    def _exec(self, argv: list[str]) -> Completed:
        exe = self.executable()
        if exe is None:
            self.state = ProviderState.DISABLED
            raise ModelError(f"`{self.binary}` is not on PATH")
        self.scratch_dir.mkdir(parents=True, exist_ok=True)
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                [exe, *argv],
                cwd=self.scratch_dir,
                env=self.env(),
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            self.state = ProviderState.LIMITED
            raise ModelTimeout(f"`{self.binary}` timed out after {self.timeout_s:.0f}s") from exc
        return Completed(
            proc.returncode, proc.stdout, proc.stderr, int((time.monotonic() - t0) * 1000)
        )


def classify_failure(text: str, binary: str) -> ModelError:
    """The right ModelError for a failed run's output."""
    if RATE_LIMIT_RE.search(text):
        return ModelRateLimited(f"{binary}: {text.strip()[:300]}", limit_hint(text))
    if AUTH_RE.search(text):
        return ModelAuthError(f"{binary}: {text.strip()[:300]}")
    return ModelError(f"{binary} failed: {text.strip()[:500]}")
