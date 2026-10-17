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


def check_draft(text: str, course: str) -> None:
    """Raise ``SeedingError`` for a draft ``apply`` couldn't load, so an editor can say so when
    the draft is saved rather than at apply time. Its ``course`` must stay the folder's: apply
    files the concepts under the course the draft names."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SeedingError(f"Not valid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise SeedingError("A draft is a mapping with course, reviewed and concepts")
    if doc.get("course") != course:
        raise SeedingError(f"This is a {course} draft; keep `course: {course}`")
    if not isinstance(doc.get("reviewed", False), bool):
        raise SeedingError("reviewed must be true or false")
    items = doc.get("concepts") or []
    if not isinstance(items, list):
        raise SeedingError("concepts must be a list")
    for n, item in enumerate(items, start=1):
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise SeedingError(f"Concept {n} needs a name")
        module = item.get("module")
        if module is not None and not isinstance(module, str):
            raise SeedingError(f"{name!r}: module must be a name or null")
        for key in ("prerequisites", "exam_tags", "aliases"):
            value = item.get(key)
            if value is not None and not (
                isinstance(value, list) and all(isinstance(v, str) for v in value)
            ):
                raise SeedingError(f"{name!r}: {key} must be a list of names")
        # A number, as apply reads it (2.0 is week 2). Apply would turn "3" into no week and
        # true into week 1, silently, so those are refused here.
        week = item.get("week")
        if week is not None and (not isinstance(week, int | float) or isinstance(week, bool)):
            raise SeedingError(f"{name!r}: week must be a number or null")


def is_reviewed(path: Path) -> bool:
    """What ``apply`` checks first; a draft that doesn't parse isn't reviewed."""
    try:
        doc = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return False
    return isinstance(doc, dict) and doc.get("reviewed") is True


@dataclass(frozen=True)
class ApplyResult:
    added: list[Concept]
    updated: list[Concept]
    unchanged: list[Concept]
    retired: list[Concept]  # in the database, missing from the draft: kept, marked retired
    unknown_prerequisites: list[str]  # named as prerequisites but not in the draft

    @property
    def applied(self) -> list[Concept]:
        return [*self.added, *self.updated, *self.unchanged]


def _names(item: dict[str, Any]) -> list[str]:
    aliases = item.get("aliases") or []
    if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
        raise SeedingError(f"{item.get('name')!r}: aliases must be a list of names")
    return [item["name"], *aliases]


def apply(path: Path, learner: LearnerMemory) -> ApplyResult:
    """Upsert the reviewed draft into ``concepts`` by concept id (BL-040, P46).

    A concept whose id isn't in the database but one of its ``aliases`` is keeps that existing
    row (a rename). Concepts of the course that the draft no longer lists are marked
    ``retired``, never deleted; their mastery and evidence are untouched. Idempotent.
    """
    if not path.exists():
        raise SeedingError(f"No draft at {path}; run `brightlearn concepts seed` first")
    doc = yaml.safe_load(path.read_text()) or {}
    if doc.get("reviewed") is not True:
        raise DraftNotReviewed(f"{path} still says `reviewed: false`; review it, then flip it")
    course = doc["course"]
    items = doc.get("concepts") or []
    existing = {c.concept_id: c for c in learner.concepts(course, include_retired=True)}

    resolved: list[tuple[dict[str, Any], str]] = []
    lookup: dict[str, str] = {}  # slug of any name or alias -> the id it resolved to
    for item in items:
        names = _names(item)
        ids = [concept_id(course, n) for n in names]
        cid = next((i for i in ids if i in existing), ids[0])
        if cid in {c for _, c in resolved}:
            raise SeedingError(f"Two concepts in the draft map to {cid}; merge them or rename one")
        resolved.append((item, cid))
        lookup.update({slug(n): cid for n in names})

    added, updated, unchanged = [], [], []
    for item, cid in resolved:
        week = item.get("week")
        concept = Concept(
            concept_id=cid,
            course=course,
            name=item["name"],
            module=item.get("module"),
            prerequisites=[
                lookup.get(slug(p), concept_id(course, p)) for p in item.get("prerequisites") or []
            ],
            exam_tags=list(item.get("exam_tags") or []),
            week=int(week) if isinstance(week, int | float) else None,
        )
        before = existing.get(cid)
        learner.upsert_concept(concept)
        if before is None:
            added.append(concept)
        elif before != concept:
            updated.append(concept)
        else:
            unchanged.append(concept)

    kept = {cid for _, cid in resolved}
    retired = [c for cid, c in existing.items() if cid not in kept and c.status == "active"]
    for concept in retired:
        learner.retire_concept(concept.concept_id)
    wanted = {p for item in items for p in item.get("prerequisites") or []}
    unknown = sorted(p for p in wanted if slug(p) not in lookup)
    return ApplyResult(added, updated, unchanged, retired, unknown)
