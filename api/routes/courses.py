"""Courses: the home page lists them and creates them. Both are DB-only, on the request's own
connection; nothing here waits for a worker."""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import ConfigDep, DbDep, EngineDep
from api.schemas.courses import CourseIn, CourseOut
from core.memory.db import Courses, Manifest
from core.memory.learner import LearnerMemory

router = APIRouter(tags=["courses"])


@router.get("/courses")
def list_courses(conn: DbDep, engine: EngineDep) -> list[CourseOut]:
    manifest, learner = Manifest(conn), LearnerMemory(conn)
    live = engine.live_sessions()
    return [
        CourseOut.from_core(
            row,
            manifest.all(row.course),
            len(learner.concepts(row.course)),
            live.get(row.course),
        )
        for row in Courses(conn).all()
    ]


@router.post("/courses", status_code=201)
def create_course(body: CourseIn, conn: DbDep, cfg: ConfigDep) -> CourseOut:
    """A duplicate is a 409 (``duplicate_course``), a code or term that can't be a folder name a
    422, both raised by ``Courses.add``."""
    row = Courses(conn).add(body.course.upper(), body.name, body.term or cfg.term)
    return CourseOut.from_core(row, [], 0, None)
