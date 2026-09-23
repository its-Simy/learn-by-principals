"""Synced files -> NotebookLM sources. Changed files replace their source (remove, then add).

Sources already in the notebook keep their slot; new ones fill the remaining slots under the
per-notebook cap in bucket priority order, and whatever doesn't fit is marked ``deferred``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from pathlib import Path

from core.memory.db import Manifest, ResourceRow
from core.providers.knowledge.base import KnowledgeProvider, KnowledgeRateLimited

log = logging.getLogger(__name__)

PRIORITY = ("syllabus", "exams", "lectures", "readings", "labs", "assignments")
CODE_BUCKETS = ("code", "other")
DEFAULT_SOURCE_CAP = 50


@dataclass
class LinkReport:
    course: str
    added: int = 0
    replaced: int = 0
    deferred: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)


def _rank(row: ResourceRow) -> tuple[int, int]:
    order = (*PRIORITY, *CODE_BUCKETS)
    bucket = row.bucket or "other"
    return (order.index(bucket) if bucket in order else len(order), row.topic_id)


class LinkStep:
    def __init__(
        self,
        knowledge: KnowledgeProvider,
        db: Manifest,
        source_cap: int = DEFAULT_SOURCE_CAP,
        include_code: bool = False,
    ) -> None:
        self._knowledge = knowledge
        self._db = db
        self._cap = source_cap
        self._include_code = include_code

    def run(self, course: str) -> LinkReport:
        report = LinkReport(course=course)
        rows = [
            r
            for r in self._db.all(course, states=["synced", "stale", "deferred"])
            if self._include_code or r.bucket not in CODE_BUCKETS
        ]
        if not rows:
            return report
        try:
            notebook_id = self._knowledge.ensure_notebook(course)
        except Exception as exc:
            log.exception("No NotebookLM notebook for %s", course)
            report.failed += 1
            report.failures.append(f"notebook: {exc}")
            return report

        linked = [r for r in rows if r.notebook_source_id]
        free = self._cap - len(linked)
        try:
            for row in linked:
                if row.sync_state == "stale":
                    self._replace(notebook_id, row, report)

            waiting = sorted((r for r in rows if not r.notebook_source_id), key=_rank)
            for row in waiting:
                if free > 0:
                    if self._add(notebook_id, row, report):
                        free -= 1
                    continue
                if row.sync_state != "deferred":
                    self._db.upsert(replace(row, sync_state="deferred"))
                report.deferred += 1
        except KnowledgeRateLimited as exc:
            log.warning("NotebookLM rate limited; stopping %s link step", course)
            report.failures.append(f"stopped, rate limited: {exc}")
        return report

    def _add(self, notebook_id: str, row: ResourceRow, report: LinkReport) -> bool:
        try:
            source_id = self._knowledge.add_file(notebook_id, Path(row.local_path or ""))
        except KnowledgeRateLimited:
            report.failed += 1
            raise
        except Exception as exc:
            self._fail(row, report, exc)
            return False
        self._db.upsert(
            replace(
                row,
                notebook_id=notebook_id,
                notebook_source_id=source_id,
                source_hash=row.hash,
                sync_state="synced",
            )
        )
        report.added += 1
        return True

    def _replace(self, notebook_id: str, row: ResourceRow, report: LinkReport) -> None:
        try:
            self._knowledge.remove_source(row.notebook_source_id or "")
        except KnowledgeRateLimited:
            report.failed += 1
            raise
        except Exception as exc:
            self._fail(row, report, exc)
            return
        # The old source is gone; record that before adding, so a failed add retries as new.
        row = replace(row, notebook_source_id=None, source_hash=None)
        self._db.upsert(row)
        if self._add(notebook_id, row, report):
            report.added -= 1
            report.replaced += 1

    def _fail(self, row: ResourceRow, report: LinkReport, exc: Exception) -> None:
        log.exception("NotebookLM link failed for topic %s", row.topic_id)
        report.failed += 1
        report.failures.append(f"topic {row.topic_id} {row.title!r}: {exc}")
