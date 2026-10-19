"""Sources: a course's stored files, uploads and the link job that sends them to NotebookLM."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from api.schemas.system import JobOut
from core.memory.db import ResourceRow

# core.memory.schema.SYNC_STATES, spelled out so the web client's generated types carry it
# (a test pins the two together).
SyncState = Literal["synced", "stale", "failed", "link", "deferred"]


class SourceOut(BaseModel):
    """``synced`` means stored, not in NotebookLM; ``linked`` says whether NotebookLM has it."""

    resource_id: str
    filename: str | None
    bucket: str | None
    size: int | None
    sync_state: SyncState
    notebook_source_id: str | None
    linked: bool
    added_at: str

    @classmethod
    def from_core(cls, row: ResourceRow) -> SourceOut:
        return cls(
            resource_id=row.resource_id,
            filename=row.filename,
            bucket=row.bucket,
            size=row.size,
            sync_state=row.sync_state,
            notebook_source_id=row.notebook_source_id,
            linked=row.notebook_source_id is not None,
            added_at=row.added_at,
        )


class UploadOut(BaseModel):
    """The stored files, and the link job that will send them to NotebookLM."""

    imported: list[SourceOut]
    job: JobOut
