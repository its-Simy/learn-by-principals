from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path

from core.providers.lms.base import Course, DownloadResult, LMSProvider, Resource


@dataclass
class FakeFile:
    filename: str
    content: bytes


class FakeLMS(LMSProvider):
    def __init__(self, courses: list[Course]) -> None:
        self.courses = courses
        self.resources: dict[int, list[Resource]] = {c.org_unit_id: [] for c in courses}
        self.files: dict[int, FakeFile] = {}
        self.fail_topics: set[int] = set()
        self.fail_courses: set[int] = set()
        self.downloads: list[int] = []
        self.sessions_ensured = 0

    def add(self, resource: Resource, filename: str | None = None, content: bytes = b"") -> None:
        self.resources[resource.org_unit_id].append(resource)
        if filename is not None:
            self.files[resource.topic_id] = FakeFile(filename, content)

    def touch(self, topic_id: int, last_modified: str, content: bytes | None = None) -> None:
        for org_unit_id, items in self.resources.items():
            self.resources[org_unit_id] = [
                replace(r, last_modified=last_modified) if r.topic_id == topic_id else r
                for r in items
            ]
        if content is not None:
            self.files[topic_id].content = content

    def ensure_session(self) -> None:
        self.sessions_ensured += 1

    def list_courses(self) -> list[Course]:
        return list(self.courses)

    def list_resources(self, org_unit_id: int) -> list[Resource]:
        if org_unit_id in self.fail_courses:
            raise RuntimeError("HTTP 403")
        return list(self.resources[org_unit_id])

    def download(self, resource: Resource, dest: Path) -> DownloadResult:
        self.downloads.append(resource.topic_id)
        f = self.files[resource.topic_id]
        dest.write_bytes(f.content)  # written before failing, so cleanup is exercised
        if resource.topic_id in self.fail_topics:
            raise RuntimeError("connection reset")
        return DownloadResult(
            path=dest,
            filename=f.filename,
            size=len(f.content),
            md5=hashlib.md5(f.content).hexdigest(),
            content_type=None,
        )
