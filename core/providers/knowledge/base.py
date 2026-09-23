"""Grounded intelligence over course sources (NotebookLM in V1)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.providers.state import ProviderState

__all__ = [
    "Citation",
    "GroundedAnswer",
    "KnowledgeError",
    "KnowledgeRateLimited",
    "KnowledgeProvider",
    "ProviderState",
    "SourceMeta",
    "notebook_title",
]


def notebook_title(course: str) -> str:
    return f"BrightLearn/{course}"


@dataclass(frozen=True)
class SourceMeta:
    source_id: str
    title: str
    kind: str
    added_at: str | None


@dataclass(frozen=True)
class Citation:
    source_id: str
    excerpt: str


@dataclass(frozen=True)
class GroundedAnswer:
    text: str
    citations: list[Citation] = field(default_factory=list)


class KnowledgeError(Exception):
    pass


class KnowledgeRateLimited(KnowledgeError):
    """Quota or rate limit hit; retrying right away won't help."""


class KnowledgeProvider(ABC):
    @abstractmethod
    def ensure_notebook(self, course: str) -> str:
        """The notebook id for ``course`` (titled ``BrightLearn/{course}``), created if missing."""

    @abstractmethod
    def add_file(self, notebook_id: str, path: Path) -> str:
        """Upload ``path`` as a new source; returns its source id."""

    @abstractmethod
    def remove_source(self, source_id: str) -> None: ...

    @abstractmethod
    def list_sources(self, notebook_id: str) -> list[SourceMeta]: ...

    @abstractmethod
    def refresh_source(self, source_id: str) -> None: ...

    @abstractmethod
    def query(
        self, notebook_id: str, question: str, source_ids: list[str] | None = None
    ) -> GroundedAnswer: ...

    @abstractmethod
    def source_fulltext(self, source_id: str) -> str: ...

    @abstractmethod
    def generate_quiz(self, notebook_id: str, spec: dict[str, Any] | None = None) -> dict: ...

    @abstractmethod
    def generate_audio(
        self, notebook_id: str, instructions_md: str, format: str, length: str
    ) -> Path:
        """Generate an Audio Overview, wait for it, and return the downloaded MP3."""

    @abstractmethod
    def generate(self, notebook_id: str, kind: str, options: dict[str, Any]) -> Path:
        """Slides, report, flashcards or mind map; returns the downloaded artifact."""

    @abstractmethod
    def health(self) -> ProviderState: ...
