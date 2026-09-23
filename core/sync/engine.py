"""Brightspace -> Drive sync: diff the TOC against the manifest, move only new or changed files.

Nothing is kept locally: each file goes to ``config.tmp_dir/{uuid}``, is uploaded and verified,
and the temp copy is deleted in a ``finally``. Manifest rows and Drive files are never deleted.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import PurePath

from core.config import Config
from core.memory.db import Manifest, ResourceRow
from core.providers.lms.base import Course, LMSProvider, Resource
from core.providers.storage.base import StorageBackend
from core.sync.classify import classify

log = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class SyncReport:
    courses: list[str] = field(default_factory=list)
    seen: int = 0
    uploaded: int = 0
    unchanged: int = 0
    links: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


class SyncEngine:
    def __init__(
        self,
        lms: LMSProvider,
        storage: StorageBackend,
        manifest: Manifest,
        config: Config,
        now: Callable[[], str] = _utcnow,
    ) -> None:
        self._lms = lms
        self._storage = storage
        self._manifest = manifest
        self._config = config
        self._now = now

    def run(self, course: str | None = None) -> SyncReport:
        """Sync every active course, or only the one whose code or org unit id is ``course``."""
        report = SyncReport()
        self._lms.ensure_session()
        courses = [c for c in self._lms.list_courses() if _matches(c, course)]
        if course and not courses:
            raise ValueError(f"No active Brightspace course matches {course!r}")
        self._config.tmp_dir.mkdir(parents=True, exist_ok=True)
        for c in courses:
            log.info("Syncing %s (%s)", c.code, c.org_unit_id)
            report.courses.append(c.code)
            try:
                resources = self._lms.list_resources(c.org_unit_id)
            except Exception as exc:
                log.exception("Could not list resources for %s", c.code)
                report.errors.append(f"{c.code}: could not list resources: {exc}")
                continue
            for resource in resources:
                report.seen += 1
                self._sync_resource(c, resource, report)
        return report

    def _sync_resource(self, course: Course, resource: Resource, report: SyncReport) -> None:
        existing = self._manifest.get(resource.topic_id)
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
            row.last_modified = resource.last_modified
            row.sync_state = "link"
            self._manifest.upsert(row)
            report.links += 1
            return

        if (
            existing is not None
            and existing.sync_state == "synced"
            and existing.drive_file_id
            and existing.last_modified == resource.last_modified
        ):
            self._manifest.upsert(row)
            report.unchanged += 1
            return

        if existing is not None and existing.sync_state == "synced":
            row.sync_state = "stale"
            self._manifest.upsert(row)

        tmp = self._config.tmp_dir / uuid.uuid4().hex
        try:
            download = self._lms.download(resource, tmp)
            bucket = classify(resource, download.filename)
            name = self._drive_name(course.code, bucket, download.filename, resource.topic_id)
            folder_id = self._storage.ensure_folder(
                f"{self._config.drive_root}/{self._config.term}/{course.code}/{bucket}"
            )
            upload = self._storage.upload(download.path, folder_id, name)
            if not self._storage.verify(upload.file_id, download.md5):
                raise RuntimeError(f"Drive md5 mismatch for {name!r} ({upload.file_id})")
            row.filename = name
            row.size = download.size
            row.hash = download.md5
            row.drive_file_id = upload.file_id
            row.drive_bucket = bucket
            row.last_modified = resource.last_modified
            row.sync_state = "synced"
            report.uploaded += 1
            log.info("%s/%s -> %s", course.code, bucket, name)
        except Exception as exc:
            log.exception("Topic %s (%r) failed", resource.topic_id, resource.title)
            row.sync_state = "failed"
            report.failed += 1
            report.errors.append(
                f"{course.code} topic {resource.topic_id} {resource.title!r}: {exc}"
            )
        finally:
            tmp.unlink(missing_ok=True)
        self._manifest.upsert(row)

    def _drive_name(self, course: str, bucket: str, filename: str, topic_id: int) -> str:
        """``filename``, unless another topic in this course bucket already owns that name."""
        owner = self._manifest.name_owner(course, bucket, filename)
        if owner is None or owner == topic_id:
            return filename
        path = PurePath(filename)
        return f"{path.stem} [{topic_id}]{path.suffix}"


def _matches(course: Course, wanted: str | None) -> bool:
    if wanted is None:
        return True
    return wanted.upper() == course.code.upper() or wanted == str(course.org_unit_id)
