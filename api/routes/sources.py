"""Sources: a course's stored files, uploads, and the link job that sends them to NotebookLM.

An upload is stored on the request's own thread and connection; only the link job talks to
NotebookLM, on the jobs worker. The link step writes back each row as it read it when it started,
so a file imported while a link job runs on its course could be overwritten: an upload refuses
while one is queued or running, and the check, the imports and the next job's submit happen under
``engine.lock``, which a retry's submit takes too.
"""

from __future__ import annotations

import errno
import shutil
import uuid
from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, UploadFile

from api.deps import ConfigDep, CourseDep, DbDep, EngineDep
from api.engine import JobRunning, Resources
from api.errors import LINK_JOB, conflicts
from api.schemas.sources import SourceOut, UploadOut
from api.schemas.system import JobOut
from core.memory.db import Courses, Manifest
from core.providers.storage.local import LocalStorageBackend, sanitize_filename
from core.sync.importer import Importer
from core.sync.link import LinkStep

router = APIRouter(tags=["sources"])

LINK_JOBS = frozenset({"link"})

# The longest file name macOS and Linux file systems take (APFS, ext4: 255 bytes of UTF-8).
MAX_NAME_BYTES = 255


class NameTooLong(ValueError):
    """A 422 (it's a ValueError): the learner renames the file."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"The file name {name[:40]!r}... is too long to store ({len(name.encode())} bytes); "
            "rename it to something shorter and upload it again."
        )


# Windows reports a name or path past its limit as WinError 206 (name too long) or 3 (path not
# found, for a path past MAX_PATH), which Python maps to ENAMETOOLONG or ENOENT.
WINDOWS_TOO_LONG = frozenset({206, 3})


def name_too_long(exc: OSError) -> bool:
    if exc.errno == errno.ENAMETOOLONG:
        return True
    return getattr(exc, "winerror", None) in WINDOWS_TOO_LONG


@router.get("/courses/{course}/sources")
def list_sources(course: CourseDep, conn: DbDep) -> list[SourceOut]:
    """Oldest upload first, the order the link step fills NotebookLM's slots in."""
    return [SourceOut.from_core(row) for row in Manifest(conn).all(course)]


@router.post("/courses/{course}/sources/upload", responses=conflicts(LINK_JOB))
def upload(
    course: CourseDep,
    files: Annotated[list[UploadFile], File()],
    conn: DbDep,
    cfg: ConfigDep,
    engine: EngineDep,
    bucket: Annotated[str | None, Form()] = None,
) -> UploadOut:
    """Store each file in its bucket (``bucket`` for all of them, else classified by name), then
    queue one link job. An unknown bucket is a 422 before anything is stored; a file that can't
    be stored (a name too long, say) is a 422 with the files before it stored and no link job
    queued, which a retry of the link picks up."""
    importer = Importer(LocalStorageBackend(cfg.storage_root), Manifest(conn), Courses(conn))
    staging = cfg.tmp_dir / uuid.uuid4().hex
    imported: list[SourceOut] = []
    with engine.lock:
        running = engine.jobs.running(course, LINK_JOBS)
        if running is not None:
            raise JobRunning(running)
        try:
            staging.mkdir(parents=True)
            # One file at a time: two uploads with the same name are two versions of one file.
            for part in files:
                name = sanitize_filename(part.filename or "")
                if len(name.encode()) > MAX_NAME_BYTES:
                    raise NameTooLong(name)
                src = staging / name
                try:
                    with src.open("wb") as out:
                        shutil.copyfileobj(part.file, out)
                    result = importer.import_file(src, course, name, bucket or None)
                except OSError as exc:
                    # Storing derives longer names (a replaced file's ``_versions`` copy), which
                    # can pass the limit when the name itself is close to it.
                    if name_too_long(exc):
                        raise NameTooLong(name) from exc
                    raise
                imported.append(SourceOut.from_core(result.row))
        finally:
            shutil.rmtree(staging, ignore_errors=True)  # doctor's "Temp dir" check sees leftovers
        job = engine.jobs.submit("link", course, link_job(course))
    return UploadOut(imported=imported, job=JobOut.from_core(job))


@router.post("/courses/{course}/sources/link")
def link(course: CourseDep, engine: EngineDep) -> JobOut:
    """The retry: the link step adds every stored file NotebookLM doesn't have yet and replaces
    the stale ones, so running it again picks up whatever failed last time. While a link job is
    already queued or running on the course, that job is returned rather than a second queued:
    uploads are refused until it ends, so it has every stored file a second one would."""
    with engine.lock:  # never mid-way through an upload's imports
        job = engine.jobs.running(course, LINK_JOBS) or engine.jobs.submit(
            "link", course, link_job(course)
        )
    return JobOut.from_core(job)


def link_job(course: str) -> Callable[[Resources], dict[str, Any]]:
    """Runs on the jobs worker with its own connection and NotebookLM provider; only the course
    code crosses threads."""

    def run(r: Resources) -> dict[str, Any]:
        report = LinkStep(r.knowledge, r.manifest, r.config.nlm_source_cap).run(course)
        return asdict(report)

    return run
