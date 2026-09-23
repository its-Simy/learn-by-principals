"""Reasoning models (Claude Code, Codex) behind one interface, so an API swap costs nothing."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.providers.state import ProviderState

__all__ = [
    "ModelError",
    "ModelProvider",
    "ModelRateLimited",
    "ModelResult",
    "ModelTimeout",
    "ProviderState",
    "TaskPackage",
    "UsageHint",
]


@dataclass(frozen=True)
class UsageHint:
    """Whatever the provider reveals about usage. A hint only: the ledger is the truth."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    limit_message: str | None = None  # e.g. "usage limit reached, resets 3pm"
    resets_at: str | None = None
    raw: dict[str, Any] | None = None


@dataclass
class TaskPackage:
    task_type: str
    persona: str | None
    system: str
    user: str
    max_output_tokens: int = 1024
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelResult:
    text: str
    provider: str
    model: str | None
    duration_ms: int
    usage_hint: UsageHint | None = None


class ModelError(Exception):
    pass


class ModelRateLimited(ModelError):
    def __init__(self, message: str, hint: UsageHint | None = None) -> None:
        super().__init__(message)
        self.hint = hint


class ModelTimeout(ModelError):
    pass


class ModelProvider(ABC):
    name: str

    @abstractmethod
    def run(self, task: TaskPackage) -> ModelResult: ...

    @abstractmethod
    def health(self) -> ProviderState: ...

    @abstractmethod
    def usage_hint(self) -> UsageHint | None: ...
