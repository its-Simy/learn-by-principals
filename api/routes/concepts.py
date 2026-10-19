"""The Studio's concepts card: what ``brightlearn concepts seed|apply`` does, plus the review step
in between that the CLI leaves to a text editor (list, read and save a draft)."""

from __future__ import annotations

import os
import uuid
from functools import partial
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from api.deps import ConfigDep, CourseDep, DbDep, EngineDep, named_file
from api.engine import Resources
from api.errors import ASK_RUNNING, SESSION_OPEN, conflicts, refuse_while_asking
from api.schemas.studio import ApplyIn, ApplyOut, ConceptOut, DraftOut, EvidenceOut
from api.schemas.system import JobOut, TextIn, TextOut
from core.config import Config
from core.memory.learner import LearnerMemory
from core.memory.seeding import (
    apply,
    check_draft,
    draft_diff,
    drafts_dir,
    is_reviewed,
    latest_draft,
    list_drafts,
    seed,
)
from core.sessions import guard

router = APIRouter(tags=["concepts"])


@router.get("/courses/{course}/concepts")
def list_concepts(
    course: CourseDep, conn: DbDep, include_retired: bool = False
) -> list[ConceptOut]:
    """Active concepts unless asked: a retired one keeps its row, mastery and evidence but drops
    out of every list (BL-040)."""
    learner = LearnerMemory(conn)
    return [
        ConceptOut.from_core(c, learner.get_mastery(c.concept_id))
        for c in learner.concepts(course, include_retired=include_retired)
    ]


@router.get("/courses/{course}/concepts/evidence")
def list_evidence(course: CourseDep, conn: DbDep, concept_id: str) -> list[EvidenceOut]:
    learner = LearnerMemory(conn)
    concept = learner.get_concept(concept_id)
    if concept is None or concept.course != course:
        raise HTTPException(404, f"No concept {concept_id!r} in {course}")
    return [EvidenceOut.from_core(e) for e in learner.evidence(concept_id)]


@router.post("/courses/{course}/concepts/seed", responses=conflicts(SESSION_OPEN, ASK_RUNNING))
def seed_concepts(course: CourseDep, conn: DbDep, engine: EngineDep) -> JobOut:
    """The seed query starts a fresh NotebookLM conversation, which would end a live tutor's
    (P66) or an ask's still being answered (P100): refuse now, under the lock a session start
    and an ask take, so neither slips past the other."""
    with engine.lock:
        guard(LearnerMemory(conn), course)
        refuse_while_asking(engine, course)
        job = engine.jobs.submit("seed", course, partial(seed_job, course))
    return JobOut.from_core(job)


def seed_job(course: str, r: Resources) -> dict[str, Any]:
    guard(r.learner, course)  # again on this thread: a CLI session may have opened since
    previous = latest_draft(r.config.vault_root, course)
    path, concepts = seed(r.knowledge, r.manifest, course, r.config.vault_root)
    return {
        "draft": path.name,
        "previous": previous.name if previous else None,
        "count": len(concepts),
        "diff": draft_diff(previous, path),
    }


@router.get("/courses/{course}/concepts/drafts")
def list_course_drafts(course: CourseDep, cfg: ConfigDep) -> list[DraftOut]:
    """Newest first."""
    drafts = list_drafts(cfg.vault_root, course)
    return [DraftOut.from_core(p, is_reviewed(p), latest=p == drafts[-1]) for p in reversed(drafts)]


@router.get("/courses/{course}/concepts/drafts/{name}")
def get_draft(course: CourseDep, name: str, cfg: ConfigDep) -> TextOut:
    return TextOut(text=draft_path(cfg, course, name).read_text(encoding="utf-8"))


@router.get("/courses/{course}/concepts/drafts/{name}/diff")
def draft_changes(course: CourseDep, name: str, cfg: ConfigDep) -> TextOut:
    """A unified diff from the draft before this one ("" for the first), as the seed job showed
    it, so the editor can show it again after a restart. It follows any edits since."""
    path = draft_path(cfg, course, name)
    drafts = list_drafts(cfg.vault_root, course)
    position = drafts.index(path)
    return TextOut(text=draft_diff(drafts[position - 1] if position else None, path))


@router.put("/courses/{course}/concepts/drafts/{name}")
def save_draft(course: CourseDep, name: str, body: TextIn, cfg: ConfigDep) -> DraftOut:
    """The review step: the learner's edit replaces the draft, as saving it in an editor would.
    A draft apply couldn't load is refused (422) and the file is left as it was."""
    path = draft_path(cfg, course, name)
    check_draft(body.text, course)
    part = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    try:
        part.write_text(body.text, encoding="utf-8")
        os.replace(part, path)  # never a half-written draft
    finally:
        part.unlink(missing_ok=True)
    return DraftOut.from_core(path, is_reviewed(path), path == latest_draft(cfg.vault_root, course))


@router.post("/courses/{course}/concepts/apply")
def apply_draft(
    course: CourseDep, cfg: ConfigDep, conn: DbDep, body: ApplyIn | None = None
) -> ApplyOut:
    """Load a reviewed draft (the newest unless one is named); a draft still marked
    ``reviewed: false`` is a 422, like the CLI's refusal."""
    name = body.draft if body else None
    if name is None:
        path = latest_draft(cfg.vault_root, course)
        if path is None:
            raise HTTPException(404, f"No draft for {course}; seed one first")
    else:
        path = draft_path(cfg, course, name)
    check_draft(path.read_text(encoding="utf-8"), course)
    result = apply(path, LearnerMemory(conn))
    return ApplyOut.from_core(path.name, result)


def draft_path(cfg: Config, course: str, name: str) -> Path:
    """404 unless ``name`` is one of the course's drafts, by the seeding module's names."""
    path = named_file(drafts_dir(cfg.vault_root, course), name, what="draft")
    if path not in list_drafts(cfg.vault_root, course):
        raise HTTPException(404, f"No draft {name!r}")
    return path
