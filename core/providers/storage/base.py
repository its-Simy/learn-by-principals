from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UploadResult:
    file_id: str
    name: str
    md5: str | None
    created: bool  # False when an existing file of the same name was updated in place


@dataclass(frozen=True)
class FileMeta:
    file_id: str
    name: str
    mime_type: str
    size: int | None
    md5: str | None

    @property
    def is_folder(self) -> bool:
        return self.mime_type == "application/vnd.google-apps.folder"


class StorageError(Exception):
    pass


class StorageBackend(ABC):
    @abstractmethod
    def ensure_folder(self, path: str) -> str:
        """Create every missing segment of ``a/b/c`` and return the leaf folder id."""

    @abstractmethod
    def upload(self, local: Path, folder_id: str, name: str) -> UploadResult:
        """Upload ``local`` as ``name``. An existing file with that name is updated in place."""

    @abstractmethod
    def verify(self, file_id: str, expected_md5: str) -> bool: ...

    @abstractmethod
    def list(self, folder_id: str) -> list[FileMeta]: ...
