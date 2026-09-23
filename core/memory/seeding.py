"""Seed a course's concept graph from NotebookLM, via a draft YAML that a human reviews first.

``seed`` writes a new ``vault/courses/{course}/concepts.draft.{timestamp}.yaml`` with
``reviewed: false`` and never overwrites an earlier draft (P65); ``apply`` refuses to load a draft
until that flag has been set to ``true`` by hand.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from core.jsonutil import extract_json_array
from core.memory.db import Manifest
from core.memory.learner import Concept, LearnerMemory
from core.memory.vault import slug
from core.providers.knowledge.base import KnowledgeProvider

SEED_PROMPT = """List the concepts this course teaches, derived from the syllabus and the lecture
titles below. Reply with ONLY a JSON array, no prose, where each item is:
{{"name": str, "module": str, "week": int or null, "prerequisites": [concept names],
"exam_tags": [e.g. "midterm-1", "final"]}}
One concept per distinct idea a student could be tested on. Use the syllabus's own wording.

Lecture titles:
{titles}
"""

SEED_BUCKETS = ("syllabus", "lectures")


class SeedingError(Exception):
    pass


class DraftNotReviewed(SeedingError):
    pass


@dataclass(frozen=True)
class DraftConcept:
    name: str
    module: str | None = None
    week: int | None = None
    prerequisites: tuple[str, ...] = ()
    exam_tags: tuple[str, ...] = ()


def concept_id(course: str, name: str) -> str:
    return f"{course.lower()}/{slug(name)}"


LEGACY_DRAFT = "concepts.draft.yaml"  # the single, overwritten draft written before BL-029
_DRAFT_NAME = re.compile(r"^concepts\.draft\.(\d{8}-\d{6})(?:-(\d+))?\.yaml$")


def drafts_dir(vault_root: Path, course: str) -> Path:
    return vault_root / "courses" / course


def _draft_order(path: Path) -> tuple[str, int]:
    match = _DRAFT_NAME.match(path.name)
    if match is None:  # the legacy draft is older than every timestamped one
        return ("", 0)
    return (match.group(1), int(match.group(2) or 0))


def list_drafts(vault_root: Path, course: str) -> list[Path]:
    """Every concept draft for ``course``, oldest first."""
    folder = drafts_dir(vault_root, course)
    if not folder.is_dir():
        return []
    drafts = [p for p in folder.iterdir() if p.name == LEGACY_DRAFT or _DRAFT_NAME.match(p.name)]
    return sorted(drafts, key=_draft_order)


def latest_draft(vault_root: Path, course: str) -> Path | None:
    drafts = list_drafts(vault_root, course)
    return drafts[-1] if drafts else None


def new_draft_path(vault_root: Path, course: str, now: datetime | None = None) -> Path:
    """``concepts.draft.{YYYYmmdd-HHMMSS}.yaml``, with ``-N`` added if that name is taken."""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    folder = drafts_dir(vault_root, course)
    path, n = folder / f"concepts.draft.{stamp}.yaml", 1
    while path.exists():
        n += 1
        path = folder / f"concepts.draft.{stamp}-{n}.yaml"
    return path


def draft_diff(previous: Path | None, current: Path) -> str:
    """Unified diff from ``previous`` to ``current`` ("" when there is no previous draft)."""
    if previous is None:
        return ""
    return "".join(
        difflib.unified_diff(
            previous.read_text().splitlines(keepends=True),
            current.read_text().splitlines(keepends=True),
            fromfile=previous.name,
            tofile=current.name,
        )
    )


def parse_concepts(text: str) -> list[DraftConcept]:
    """The JSON array in a model answer, tolerating code fences and surrounding prose."""
    items = extract_json_array(text)
    if not items:
        raise SeedingError("No JSON array of concepts in the NotebookLM answer")
    concepts = []
    for item in items:
        if not isinstance(item, dict) or not str(item.get("name", "")).strip():
            continue
        week = item.get("week")
        concepts.append(
            DraftConcept(
                name=str(item["name"]).strip(),
                module=item.get("module") or None,
                week=int(week) if isinstance(week, int | float) else None,
                prerequisites=tuple(str(p) for p in item.get("prerequisites") or []),
                exam_tags=tuple(str(t) for t in item.get("exam_tags") or []),
            )
        )
    return concepts


def seed(
    knowledge: KnowledgeProvider,
    db: Manifest,
    course: str,
    vault_root: Path,
    now: datetime | None = None,
) -> tuple[Path, list[DraftConcept]]:
    """Query NotebookLM and write a new draft; earlier drafts are never touched."""
    rows = [r for r in db.all(course) if r.bucket in SEED_BUCKETS]
    titles = "\n".join(f"- {r.title}" for r in rows if r.bucket == "lectures") or "- (none)"
    source_ids = [r.notebook_source_id for r in rows if r.notebook_source_id] or None
    notebook_id = knowledge.ensure_notebook(course)
    answer = knowledge.query(notebook_id, SEED_PROMPT.format(titles=titles), source_ids)
    concepts = parse_concepts(answer.text)
    if not concepts:
        raise SeedingError("NotebookLM returned no concepts")
    path = new_draft_path(vault_root, course, now)
    write_draft(path, course, concepts)
    return path, concepts


def write_draft(path: Path, course: str, concepts: list[DraftConcept]) -> None:
    """Create ``path``; refuses if it already exists (a draft is never overwritten)."""
    doc: dict[str, Any] = {
        "course": course,
        "reviewed": False,
        "concepts": [
            {
                "name": c.name,
                "module": c.module,
                "week": c.week,
                "prerequisites": list(c.prerequisites),
                "exam_tags": list(c.exam_tags),
            }
            for c in concepts
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Draft from NotebookLM. Edit freely, then set `reviewed: true` and run\n"
        f"# `brightlearn concepts apply --course {course}` (newest draft; --draft picks another).\n"
    )
    with path.open("x") as f:
        f.write(header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))


@dataclass(frozen=True)
class ApplyResult:
    applied: list[Concept]
    unknown_prerequisites: list[str]  # named as prerequisites but not in the draft


def apply(path: Path, learner: LearnerMemory) -> ApplyResult:
    """Upsert the reviewed draft into ``concepts``. Idempotent; never deletes concepts."""
    if not path.exists():
        raise SeedingError(f"No draft at {path}; run `brightlearn concepts seed` first")
    doc = yaml.safe_load(path.read_text()) or {}
    if doc.get("reviewed") is not True:
        raise DraftNotReviewed(f"{path} still says `reviewed: false`; review it, then flip it")
    course = doc["course"]
    items = doc.get("concepts") or []
    applied = []
    for item in items:
        concept = Concept(
            concept_id=concept_id(course, item["name"]),
            course=course,
            name=item["name"],
            module=item.get("module"),
            prerequisites=[concept_id(course, p) for p in item.get("prerequisites") or []],
            exam_tags=list(item.get("exam_tags") or []),
            week=int(week) if isinstance(week := item.get("week"), int | float) else None,
        )
        learner.upsert_concept(concept)
        applied.append(concept)
    names = {item["name"] for item in items}
    wanted = {p for item in items for p in item.get("prerequisites") or []}
    return ApplyResult(applied, sorted(wanted - names))
