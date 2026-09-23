"""The Markdown vault: readable notes whose YAML front matter mirrors the SQLite rows.

SQLite stays the machine truth; ``vault_check`` reports notes that have drifted from it.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from core.memory.learner import Concept, Evidence, LearnerMemory, Mastery, SessionRow

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "untitled"


def concept_row(concept: Concept, mastery: Mastery | None) -> dict[str, Any]:
    """The concept row plus its mastery row, as the note's front matter records them."""
    mastery = mastery or Mastery(concept.concept_id)
    row = asdict(concept)
    row.update({k: v for k, v in asdict(mastery).items() if k != "concept_id"})
    return row


@dataclass(frozen=True)
class Mismatch:
    path: Path
    field: str
    note: Any
    db: Any


def read_front_matter(path: Path) -> dict[str, Any]:
    match = _FRONT_MATTER.match(path.read_text())
    if not match:
        return {}
    return yaml.safe_load(match.group(1)) or {}


def _write(path: Path, front_matter: dict[str, Any], body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=True).strip()
    path.write_text(f"---\n{header}\n---\n\n{body.strip()}\n")
    return path


class Vault:
    def __init__(self, root: Path) -> None:
        self.root = root

    def concept_path(self, concept: Concept) -> Path:
        return self.root / "concepts" / f"{slug(concept.concept_id)}.md"

    def session_transcript_path(self, session_id: str) -> Path:
        return self.root / "sessions" / f"{session_id}.md"

    def session_summary_path(self, session_id: str) -> Path:
        return self.root / "sessions" / f"{session_id}.summary.md"

    def write_concept_note(
        self,
        concept: Concept,
        mastery: Mastery | None,
        misconceptions: list[str],
        evidence: list[Evidence],
    ) -> Path:
        lines = [f"# {concept.name}", ""]
        if concept.prerequisites:
            lines += ["Prerequisites: " + ", ".join(concept.prerequisites), ""]
        lines += ["## Misconceptions", ""]
        lines += [f"- {m}" for m in misconceptions] or ["- none recorded"]
        lines += ["", "## Evidence", ""]
        lines += [
            f"- {e.recorded_at} · {e.type} ({e.strength})"
            + (f" · {e.source_provider}" if e.source_provider else "")
            + (f" — {e.excerpt_ref}" if e.excerpt_ref else "")
            for e in evidence
        ] or ["- none yet"]
        return _write(self.concept_path(concept), concept_row(concept, mastery), "\n".join(lines))

    def write_session_summary(
        self, session: SessionRow, summary: str = "", evidence: list[Evidence] | None = None
    ) -> Path:
        lines = [
            f"# Session {session.session_id} · {session.course}",
            "",
            summary or "(no summary)",
        ]
        if evidence:
            lines += ["", "## Evidence extracted", ""]
            lines += [f"- {e.concept_id}: {e.type} ({e.strength})" for e in evidence]
        return _write(
            self.session_summary_path(session.session_id), asdict(session), "\n".join(lines)
        )

    def vault_check(self, learner: LearnerMemory) -> list[Mismatch]:
        """Concept notes whose front matter disagrees with SQLite (or whose concept is gone)."""
        problems: list[Mismatch] = []
        for path in sorted((self.root / "concepts").glob("*.md")):
            note = read_front_matter(path)
            concept = learner.get_concept(note.get("concept_id", ""))
            if concept is None:
                problems.append(Mismatch(path, "concept_id", note.get("concept_id"), None))
                continue
            db = concept_row(concept, learner.get_mastery(concept.concept_id))
            for key in sorted(set(db) | set(note)):
                if note.get(key) != db.get(key):
                    problems.append(Mismatch(path, key, note.get(key), db.get(key)))
        return problems
