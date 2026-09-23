"""Brightspace -> local storage sync: diff the TOC against the manifest, download only what changed.

Each file is downloaded to ``config.tmp_dir/{uuid}``, then moved into
``storage_root/{term}/{course}/{bucket}/``; the temp path is deleted in a ``finally``. Manifest
rows and stored files are never deleted.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import PurePath
from typing import TypeVar

from core.config import Config
from core.memory.db import Manifest, ResourceRow
from core.providers.lms.base import Course, LMSProvider, Resource, SessionExpired
from core.providers.storage.base import StorageBackend
from core.sync.classify import classify

log = logging.getLogger(__name__)

T = TypeVar("T")

# States whose local file is current as of the row's last_modified.
_UP_TO_DATE = frozenset({"synced", "stale"})


def _utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class SyncReport:
    course: str
    new: int = 0
    changed: int = 0
    skipped: int = 0
    links: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)


class SyncEngine:
    def __init__(
        self,
        lms: LMSProvider,
        storage: StorageBackend,
        db: Manifest,
        config: Config,
        now: Callable[[], str] = _utcnow,
    ) -> None:
        self._lms = lms
        self._storage = storage
        self._db = db
        self._config = config
        self._now = now

    def sync_course(
        self, course: Course, term: str, dry_run: bool = False, force: bool = False
    ) -> SyncReport:
        """Sync one course. ``dry_run`` reads Brightspace but writes nothing; ``force``
        re-downloads files the manifest says are current."""
        report = SyncReport(course=course.code)
        try:
            resources = self._with_session(lambda: self._lms.list_resources(course.org_unit_id))
        except Exception as exc:
            log.exception("Could not list resources for %s", course.code)
            report.failures.append(f"could not list resources: {exc}")
            return report
        if not dry_run:
            self._config.tmp_dir.mkdir(parents=True, exist_ok=True)
        for resource in resources:
            self._sync_resource(course, term, resource, report, dry_run, force)
        return report

    def _with_session(self, call: Callable[[], T]) -> T:
        try:
            return call()
        except SessionExpired:
            log.warning("Brightspace session expired; re-establishing and retrying once")
            self._lms.ensure_session()
            return call()

    def _sync_resource(
        self,
        course: Course,
        term: str,
        resource: Resource,
        report: SyncReport,
        dry_run: bool,
        force: bool,
    ) -> None:
        existing = self._db.get(resource.topic_id)
        row = replace(
            existing
            or ResourceRow(
                course=course.code,
                org_unit_id=course.org_unit_id,
                topic_id=resource.topic_id,
                module_path=resource.module_path,
                title=resource.title,
                type_identifier=resource.type_identifier,
                last_seen="",
            ),
            course=course.code,
            org_unit_id=course.org_unit_id,
            module_path=resource.module_path,
            title=resource.title,
            type_identifier=resource.type_identifier,
            last_seen=self._now(),
        )

        if resource.type_identifier != "File":
            report.links += 1
            if not dry_run:
                row.url = resource.url
                row.last_modified = resource.last_modified
                row.sync_state = "link"
                self._db.upsert(row)
            return

        if (
            not force
            and existing is not None
            and existing.sync_state in _UP_TO_DATE
            and existing.last_modified == resource.last_modified
        ):
            report.skipped += 1
            if not dry_run:
                self._db.upsert(row)
            return

        if dry_run:
            if existing is None or existing.hash is None:
                report.new += 1
            else:
                report.changed += 1
            return

        tmp = self._config.tmp_dir / uuid.uuid4().hex
        try:
            download = self._with_session(lambda: self._lms.download(resource, tmp))
            bucket = classify(resource, download.filename)
            name = self._local_name(course.code, bucket, download.filename, resource.topic_id)
            stored = self._storage.store(tmp, f"{term}/{course.code}/{bucket}", name)
            old_hash = existing.hash if existing else None
            if old_hash is None:
                report.new += 1
            elif old_hash != stored.sha256:
                report.changed += 1
            else:
                report.skipped += 1
            # stale: the NotebookLM copy (BL-015) is older than this file.
            stale = (old_hash is not None and old_hash != stored.sha256) or (
                existing is not None and existing.sync_state == "stale"
            )
            row.filename = stored.path.name
            row.local_path = str(stored.path)
            row.bucket = bucket
            row.hash = stored.sha256
            row.size = stored.size
            row.last_modified = resource.last_modified
            row.sync_state = "stale" if stale else "synced"
            log.info("%s/%s -> %s", course.code, bucket, stored.path.name)
        except Exception as exc:
            log.exception("Topic %s (%r) failed", resource.topic_id, resource.title)
            row.sync_state = "failed"
            report.failed += 1
            report.failures.append(f"topic {resource.topic_id} {resource.title!r}: {exc}")
        finally:
            tmp.unlink(missing_ok=True)
        self._db.upsert(row)

    def _local_name(self, course: str, bucket: str, filename: str, topic_id: int) -> str:
        """``filename``, unless another topic in this course bucket already owns that name."""
        owner = self._db.name_owner(course, bucket, filename)
        if owner is None or owner == topic_id:
            return filename
        path = PurePath(filename)
        return f"{path.stem} [{topic_id}]{path.suffix}"


def select_courses(courses: list[Course], wanted: str | None) -> list[Course]:
    """Every course, or only the one whose code or org unit id is ``wanted``."""
    if wanted is None:
        return list(courses)
    return [c for c in courses if wanted.upper() == c.code.upper() or wanted == str(c.org_unit_id)]
