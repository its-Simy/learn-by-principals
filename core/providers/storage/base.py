from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoreResult:
    path: Path  # absolute
    sha256: str
    size: int


class StorageError(Exception):
    pass


class StorageBackend(ABC):
    @abstractmethod
    def ensure_folder(self, path: str) -> Path:
        """Create ``root/path`` if missing and return its absolute path."""

    @abstractmethod
    def store(self, src: Path, rel_dir: str, name: str) -> StoreResult:
        """Move ``src`` to ``rel_dir/name``. The hash is computed on write."""

    @abstractmethod
    def exists(self, rel_path: str) -> bool: ...

    @abstractmethod
    def list(self, rel_dir: str) -> list[Path]: ...
