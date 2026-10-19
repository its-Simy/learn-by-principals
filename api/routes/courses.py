"""Courses: the home page lists them and creates them. Both are DB-only, on the request's own
connection; nothing here waits for a worker."""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import ConfigDep, DbDep, EngineDep
from api.errors import DUPLICATE_COURSE, Refused, conflicts
from api.schemas.courses import CourseIn, CourseOut
from core.memory.db import BadFolderName, Courses, Manifest
from core.memory.learner import LearnerMemory

router = APIRouter(tags=["courses"])

# The 422 code for each field ``Courses.add`` can refuse, so the dialog puts the error under it.
FIELD_CODES = {"course": "invalid_course_code", "term": "invalid_term"}


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


@router.post("/courses", status_code=201, responses=conflicts(DUPLICATE_COURSE))
def create_course(body: CourseIn, conn: DbDep, cfg: ConfigDep) -> CourseOut:
    """The dialog sends only a name; the code is derived from it (``Courses.code_for``). A duplicate
    is a 409 (``duplicate_course``), a code or term that can't be a folder name a 422
    (``invalid_course_code``, ``invalid_term``), both raised by ``Courses.add``."""
    courses = Courses(conn)
    code = body.course.upper() if body.course else courses.code_for(body.name)
    try:
        row = courses.add(code, body.name, body.term or cfg.term)
    except BadFolderName as exc:
        raise Refused(FIELD_CODES[exc.field], str(exc)) from exc
    return CourseOut.from_core(row, [], 0, None)
