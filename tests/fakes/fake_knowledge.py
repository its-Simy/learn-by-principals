from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.providers.knowledge.base import (
    Citation,
    GroundedAnswer,
    KnowledgeError,
    KnowledgeProvider,
    ProviderState,
    SourceMeta,
    notebook_title,
)


@dataclass
class FakeSource:
    source_id: str
    notebook_id: str
    path: Path
    text: str


class FakeKnowledge(KnowledgeProvider):
    """Sources held in memory; queries answered with ``answer_text``, citing the first source."""

    def __init__(self, out_dir: Path | None = None, answer_text: str = "Canned answer.") -> None:
        self.out_dir = out_dir
        self.answer_text = answer_text
        self.quiz: dict[str, Any] = {"questions": [{"question": "Q1?", "answer": "A1"}]}
        self.notebooks: dict[str, str] = {}  # title -> id
        self.sources: dict[str, FakeSource] = {}
        self.calls: list[tuple[str, Any]] = []
        self.queries: list[tuple[str, str, list[str] | None]] = []
        self.state = ProviderState.AVAILABLE
        self._ids = itertools.count(1)

    def ensure_notebook(self, course: str) -> str:
        title = notebook_title(course)
        if title not in self.notebooks:
            self.notebooks[title] = f"nb{next(self._ids)}"
        return self.notebooks[title]

    def add_file(self, notebook_id: str, path: Path) -> str:
        self.calls.append(("add_file", path))
        source_id = f"src{next(self._ids)}"
        text = path.read_text(errors="replace") if path.exists() else ""
        self.sources[source_id] = FakeSource(source_id, notebook_id, path, text)
        return source_id

    def remove_source(self, source_id: str) -> None:
        self.calls.append(("remove_source", source_id))
        if self.sources.pop(source_id, None) is None:
            raise KnowledgeError(f"no source {source_id}")

    def list_sources(self, notebook_id: str) -> list[SourceMeta]:
        return [
            SourceMeta(s.source_id, s.path.name, "pdf", None)
            for s in self.sources.values()
            if s.notebook_id == notebook_id
        ]

    def refresh_source(self, source_id: str) -> None:
        self.calls.append(("refresh_source", source_id))

    def query(
        self, notebook_id: str, question: str, source_ids: list[str] | None = None
    ) -> GroundedAnswer:
        self.queries.append((notebook_id, question, source_ids))
        pool = [
            s
            for s in self.sources.values()
            if s.notebook_id == notebook_id and (source_ids is None or s.source_id in source_ids)
        ]
        citations = [Citation(s.source_id, s.text[:80]) for s in pool[:1]]
        return GroundedAnswer(self.answer_text, citations)

    def source_fulltext(self, source_id: str) -> str:
        return self.sources[source_id].text

    def generate_quiz(self, notebook_id: str, spec: dict[str, Any] | None = None) -> dict:
        self.calls.append(("generate_quiz", spec))
        return self.quiz

    def generate_audio(
        self, notebook_id: str, instructions_md: str, format: str, length: str
    ) -> Path:
        self.calls.append(("generate_audio", (instructions_md, format, length)))
        return self._artifact("audio.mp3", b"ID3fake")

    def generate(self, notebook_id: str, kind: str, options: dict[str, Any]) -> Path:
        self.calls.append(("generate", (kind, options)))
        if kind == "flashcards":
            return self._artifact("flashcards.json", json.dumps({"cards": []}).encode())
        return self._artifact(f"{kind}.md", f"# {kind}\n".encode())

    def health(self) -> ProviderState:
        return self.state

    def _artifact(self, name: str, content: bytes) -> Path:
        if self.out_dir is None:
            raise KnowledgeError("FakeKnowledge needs out_dir to generate artifacts")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"{next(self._ids)}-{name}"
        path.write_bytes(content)
        return path
