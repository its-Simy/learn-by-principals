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
VERSIONS_DIR = "_versions"
_CHUNK = 1 << 20


# Names Windows reserves for devices, with or without an extension (CON.pdf is still CON).
RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)


def sanitize_filename(name: str) -> str:
    """Strip path separators, control characters and what Windows won't take (``<>:"|?*``,
    trailing dots or spaces, device names), collapse whitespace, keep the extension."""
    name = re.sub(r'[/\\\x00-\x1f<>:"|?*]', "", name)
    stem, ext = os.path.splitext(name)
    stem = re.sub(r"\s+", " ", stem).strip().lstrip(".").strip()
    ext = re.sub(r"\s+", "", ext).rstrip(". ")
    if stem.upper() in RESERVED_NAMES:
        stem = f"{stem}_"
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

        Same name and same hash: the existing file is left untouched. Different hash: the old file
        is kept as ``_versions/{name}.{old_hash[:8]}`` first, then replaced (principle 3).
        """
        dest = self.ensure_folder(rel_dir) / sanitize_filename(name)
        digest, size = sha256_file(src), src.stat().st_size
        if dest.is_file():
            old = sha256_file(dest)
            if old == digest:
                src.unlink()
                return StoreResult(dest, digest, size)
            self._archive(dest, old)
        self._move(src, dest, digest)
        return StoreResult(dest, digest, size)

    def versions(self, rel_dir: str, name: str) -> list[Path]:
        """Earlier versions of ``rel_dir/name`` kept by ``store``."""
        folder = self._resolve(rel_dir) / VERSIONS_DIR
        prefix = sanitize_filename(name) + "."
        if not folder.is_dir():
            return []
        return sorted(p for p in folder.iterdir() if p.name.startswith(prefix))

    def exists(self, rel_path: str) -> bool:
        return self._resolve(rel_path).exists()

    def list(self, rel_dir: str) -> list[Path]:
        """Current files and folders; part files and the ``_versions`` archive are left out."""
        folder = self._resolve(rel_dir)
        if not folder.is_dir():
            return []
        return sorted(
            p
            for p in folder.iterdir()
            if not p.name.endswith(PART_SUFFIX) and p.name != VERSIONS_DIR
        )

    def _resolve(self, rel: str) -> Path:
        path = (self.root / rel).resolve()
        if path != self.root and self.root not in path.parents:
            raise StorageError(f"{rel!r} escapes the storage root")
        return path

    def _archive(self, current: Path, digest: str) -> None:
        """Keep ``current`` under ``_versions/`` before it is replaced. A hard link costs no space
        and leaves ``current`` in place, so a failed replace still leaves the old file intact."""
        versions = current.parent / VERSIONS_DIR
        versions.mkdir(exist_ok=True)
        target = versions / f"{current.name}.{digest[:8]}"
        if target.exists():
            return
        try:
            os.link(current, target)
            return
        except OSError:
            pass  # no hard links on this filesystem: copy instead
        part = versions / f".{target.name}.{uuid.uuid4().hex}{PART_SUFFIX}"
        try:
            shutil.copy2(current, part)
            os.replace(part, target)
        finally:
            part.unlink(missing_ok=True)
        log.info("Kept previous version as %s", target)

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
