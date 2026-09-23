"""Canonical course files on the local disk, under ``storage_root``."""

from __future__ import annotations

import errno
import hashlib
import logging
import os
import re
import shutil
import uuid
from pathlib import Path

from core.providers.state import ProviderState
from core.providers.storage.base import StorageBackend, StorageError, StoreResult

log = logging.getLogger(__name__)

PART_SUFFIX = ".part"
_CHUNK = 1 << 20


def sanitize_filename(name: str) -> str:
    """Strip path separators and control characters, collapse whitespace, keep the extension."""
    name = re.sub(r"[/\\\x00-\x1f]", "", name)
    stem, ext = os.path.splitext(name)
    stem = re.sub(r"\s+", " ", stem).strip().lstrip(".").strip()
    ext = re.sub(r"\s+", "", ext)
    return (stem or "untitled") + ext


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


class LocalStorageBackend(StorageBackend):
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def health(self) -> ProviderState:
        """AVAILABLE when ``root``, or the nearest existing parent, is a writable directory."""
        target = self.root
        while not target.exists() and target != target.parent:
            target = target.parent
        if target.is_dir() and os.access(target, os.W_OK | os.X_OK):
            return ProviderState.AVAILABLE
        log.warning("Storage root %s is not writable (checked %s)", self.root, target)
        return ProviderState.BROKEN

    def ensure_folder(self, path: str) -> Path:
        folder = self._resolve(path)
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def store(self, src: Path, rel_dir: str, name: str) -> StoreResult:
        """Move ``src`` into place; ``src`` is consumed either way.

        Same name and same hash: the existing file is left untouched. Different hash: overwritten.
        """
        dest = self.ensure_folder(rel_dir) / sanitize_filename(name)
        digest, size = sha256_file(src), src.stat().st_size
        if dest.is_file() and sha256_file(dest) == digest:
            src.unlink()
            return StoreResult(dest, digest, size)
        self._move(src, dest, digest)
        return StoreResult(dest, digest, size)

    def exists(self, rel_path: str) -> bool:
        return self._resolve(rel_path).exists()

    def list(self, rel_dir: str) -> list[Path]:
        folder = self._resolve(rel_dir)
        if not folder.is_dir():
            return []
        return sorted(p for p in folder.iterdir() if not p.name.endswith(PART_SUFFIX))

    def _resolve(self, rel: str) -> Path:
        path = (self.root / rel).resolve()
        if path != self.root and self.root not in path.parents:
            raise StorageError(f"{rel!r} escapes the storage root")
        return path

    def _move(self, src: Path, dest: Path, digest: str) -> None:
        try:
            os.replace(src, dest)  # atomic within one filesystem
            return
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
        # Across filesystems: copy to a hidden part file beside dest, check it, then rename.
        part = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}{PART_SUFFIX}")
        try:
            shutil.copyfile(src, part)
            if sha256_file(part) != digest:
                raise StorageError(f"Copy of {src} to {dest} does not match its hash")
            os.replace(part, dest)
        finally:
            part.unlink(missing_ok=True)
        src.unlink()
