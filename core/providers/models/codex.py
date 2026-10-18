"""Codex CLI on the ChatGPT subscription, via ``codex exec``.

Flags are NOT verified: ``codex`` wasn't installed when this was written (see problems.md).
Expected: ``codex exec [--skip-git-repo-check] [--sandbox read-only] [--color never]
[-o FILE]`` with the prompt on stdin (``codex exec`` reads it there when no prompt argument is
given). The final message is read from the ``-o`` file; the model name and token count are
parsed from the run's header/footer text, never hardcoded. ``codex exec`` has no system-prompt
flag, so the system prompt is prepended to the prompt.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from core.config import Config
from core.providers.models.base import ModelError, TaskPackage, UsageHint
from core.providers.models.cli_base import (
    RATE_LIMIT_RE,
    SCRUBBED_ENV,
    CLIModelProvider,
    Completed,
    classify_failure,
)

MODEL_RE = re.compile(r"^\s*model:\s*(\S+)", re.IGNORECASE | re.MULTILINE)
TOKENS_RE = re.compile(r"tokens used:?\s*([\d,]+)", re.IGNORECASE)


class CodexProvider(CLIModelProvider):
    name = "codex"
    binary = "codex"
    # An OpenAI API key in the environment could switch Codex to metered billing (principle 1).
    scrubbed_env = (*SCRUBBED_ENV, "OPENAI_API_KEY")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_message: Path | None = None

    @classmethod
    def from_config(cls, config: Config) -> CodexProvider:
        return cls(config.home / "scratch" / "codex", timeout_s=config.model_timeout_s)

    def argv(self, task: TaskPackage) -> list[str]:
        self._last_message = self.scratch_dir / f"last-{uuid.uuid4().hex}.txt"
        return [
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "-o",
            str(self._last_message),
        ]

    def stdin_text(self, task: TaskPackage) -> str:
        return f"{task.system}\n\n---\n\n{task.user}" if task.system else task.user

    def parse(self, done: Completed) -> tuple[str, str | None, UsageHint | None]:
        output = f"{done.stderr}\n{done.stdout}"
        text = ""
        if self._last_message is not None and self._last_message.exists():
            text = self._last_message.read_text(encoding="utf-8").strip()
            self._last_message.unlink()
        if done.returncode != 0 or not text:
            if RATE_LIMIT_RE.search(output):
                raise classify_failure(output, self.binary)
            if done.returncode != 0:
                raise classify_failure(output or f"exit {done.returncode}", self.binary)
            raise ModelError(f"codex produced no final message: {output.strip()[:300]}")
        model = MODEL_RE.search(output)
        tokens = TOKENS_RE.search(output)
        raw = {"tokens_used": int(tokens.group(1).replace(",", ""))} if tokens else None
        return text, model.group(1) if model else None, UsageHint(raw=raw)
