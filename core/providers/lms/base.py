from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Course:
    org_unit_id: int
    code: str
    name: str


@dataclass(frozen=True)
class Resource:
    org_unit_id: int
    topic_id: int
    module_path: str
    title: str
    type_identifier: str
    url: str | None
    last_modified: str | None


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    filename: str
    size: int
    md5: str
    content_type: str | None


class LMSError(Exception):
    pass


class SessionExpired(LMSError):
    """The session died mid-run; ``ensure_session()`` then retrying once should recover."""


class LMSProvider(ABC):
    @abstractmethod
    def ensure_session(self) -> None:
        """Proceed headless if the session is valid; otherwise headed login + Duo pause."""

    @abstractmethod
    def list_courses(self) -> list[Course]: ...

    @abstractmethod
    def list_resources(self, org_unit_id: int) -> list[Resource]:
        """Flattened TOC for one course."""

    @abstractmethod
    def download(self, resource: Resource, dest: Path) -> DownloadResult:
        """Write the file bytes to ``dest``; the real filename comes from Content-Disposition."""
