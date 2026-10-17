"""An uploaded course file -> ``storage_root/{term}/{course}/{bucket}/`` and a manifest row.

The link step (``core.sync.link``) then pushes stored files to NotebookLM. Manifest rows and
stored files are never deleted; a replaced file is kept in ``_versions/`` by the storage backend.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path, PurePath

from core.ledger.ledger import utcnow
from core.memory.db import Courses, Manifest, ResourceRow
from core.providers.storage.base import StorageBackend
from core.sync.classify import BUCKETS, Fallback, classify

log = logging.getLogger(__name__)


class ImportRefused(ValueError):
    """Nothing was stored, so the caller still owns ``src``."""


class UnknownCourse(ImportRefused):
    pass


class UnknownBucket(ImportRefused):
    pass


@dataclass(frozen=True)
class ImportResult:
    row: ResourceRow
    outcome: str  # new | changed | unchanged


class Importer:
    def __init__(
        self,
        storage: StorageBackend,
        db: Manifest,
        courses: Courses,
        now: Callable[[], str] = utcnow,
        classify_fallback: Fallback | None = None,
    ) -> None:
        self._storage = storage
        self._db = db
        self._courses = courses
        self._now = now
        self._classify_fallback = classify_fallback

    def import_file(
        self, src: Path, course: str, name: str, bucket: str | None = None
    ) -> ImportResult:
        """Store ``src`` as ``name`` (consuming it) and record it.

        The same name in the same bucket is a new version of that file, which is what re-uploading
        a corrected lecture should do: the row keeps its id and NotebookLM link, and turns
        ``stale`` while NotebookLM holds other bytes, so the link step replaces the source.
        """
        row = self._courses.get(course)
        if row is None:
            raise UnknownCourse(f"No course {course!r}; create it before importing files.")
        if bucket and bucket not in BUCKETS:
            raise UnknownBucket(f"Unknown bucket {bucket!r}; one of {', '.join(BUCKETS)}.")
        bucket = bucket or classify(PurePath(name).stem, name, self._classify_fallback)
        stored = self._storage.store(src, f"{row.term}/{course}/{bucket}", name)
        # Looked up by the stored name: storage sanitizes ``name`` before writing it.
        existing = self._db.find(course, bucket, stored.path.name)
        if existing is None:
            outcome = "new"
        elif existing.hash == stored.sha256:
            outcome = "unchanged"
        else:
            outcome = "changed"
        stale = (
            existing is not None
            and existing.notebook_source_id is not None
            and existing.source_hash != stored.sha256
        )
        base = existing or ResourceRow(
            resource_id=uuid.uuid4().hex, course=course, title=name, added_at=self._now()
        )
        result = replace(
            base,
            filename=stored.path.name,
            bucket=bucket,
            local_path=str(stored.path),
            hash=stored.sha256,
            size=stored.size,
            sync_state="stale" if stale else "synced",
        )
        self._db.upsert(result)
        log.info("%s/%s/%s: %s", course, bucket, stored.path.name, outcome)
        return ImportResult(result, outcome)
