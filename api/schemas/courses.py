"""Courses: the home page's grid and the new-course dialog."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, StringConstraints

from core.memory.db import CourseRow, ResourceRow

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CourseIn(BaseModel):
    course: NonBlank | None = None  # upper-cased as the CLI does; derived from the name if left out
    name: NonBlank
    term: str | None = None  # the term folder; today's term (config.term) when left out


class CourseOut(BaseModel):
    course: str
    name: str
    term: str
    created_at: str
    sources: int  # every row the Sources pane lists
    linked: int  # those NotebookLM has; ask and tutor need at least one
    concepts: int  # active concepts (retired ones are kept but not counted)
    open_session_id: str | None  # the live tutor session this server holds, if any

    @classmethod
    def from_core(
        cls,
        row: CourseRow,
        resources: list[ResourceRow],
        concepts: int,
        open_session_id: str | None,
    ) -> CourseOut:
        return cls(
            course=row.course,
            name=row.name,
            term=row.term,
            created_at=row.created_at,
            sources=len(resources),
            linked=sum(1 for r in resources if r.notebook_source_id),
            concepts=concepts,
            open_session_id=open_session_id,
        )
