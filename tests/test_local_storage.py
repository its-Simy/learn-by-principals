import errno
import hashlib
import os
import shutil

import pytest

from core.providers.state import ProviderState
from core.providers.storage.base import StorageError
from core.providers.storage.local import LocalStorageBackend, sanitize_filename

REL = "Fall-2026/CSE220/lectures"


@pytest.fixture
def storage(tmp_path):
    return LocalStorageBackend(tmp_path / "courses")


def src(tmp_path, content: bytes, name: str = "download") -> os.PathLike:
    path = tmp_path / name
    path.write_bytes(content)
    return path


def test_store_moves_file_and_reports_hash(storage, tmp_path):
    tmp = src(tmp_path, b"lecture one")
    result = storage.store(tmp, REL, "lec1.pdf")

    assert result.path == storage.root / REL / "lec1.pdf"
    assert result.path.read_bytes() == b"lecture one"
    assert result.sha256 == hashlib.sha256(b"lecture one").hexdigest()
    assert result.size == len(b"lecture one")
    assert not tmp.exists()
    assert storage.exists(f"{REL}/lec1.pdf")
    assert storage.list(REL) == [result.path]


def test_restore_identical_is_a_no_op(storage, tmp_path):
    first = storage.store(src(tmp_path, b"same"), REL, "lec1.pdf")
    before = first.path.stat()

    again = storage.store(src(tmp_path, b"same"), REL, "lec1.pdf")

    after = again.path.stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    assert again.sha256 == first.sha256


def test_restore_changed_overwrites(storage, tmp_path):
    storage.store(src(tmp_path, b"v1"), REL, "lec1.pdf")
    result = storage.store(src(tmp_path, b"v2"), REL, "lec1.pdf")

    assert result.path.read_bytes() == b"v2"
    assert result.sha256 == hashlib.sha256(b"v2").hexdigest()
    assert storage.list(REL) == [result.path]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("../../etc/passwd", "etcpasswd"),
        ("a\\b.pdf", "ab.pdf"),
        ("  Lecture   1 \t— Bits  .pptx", "Lecture 1 — Bits.pptx"),
        ("..", "untitled"),
        (".pdf", "pdf"),
        ("notes.tar. gz", "notes.tar.gz"),
        ("bad\x00name\n.c", "badname.c"),
    ],
)
def test_sanitize_filename(name, expected):
    assert sanitize_filename(name) == expected


def test_bad_filename_is_sanitized_on_store(storage, tmp_path):
    result = storage.store(src(tmp_path, b"x"), REL, "../../escape  me.pdf")
    assert result.path == storage.root / REL / "escape me.pdf"


def test_rel_dir_cannot_escape_root(storage, tmp_path):
    with pytest.raises(StorageError):
        storage.store(src(tmp_path, b"x"), "../outside", "x.pdf")


def test_cross_filesystem_move_copies_then_deletes_source(storage, tmp_path, monkeypatch):
    real_replace = os.replace
    calls = []

    def replace(a, b):
        calls.append((a, b))
        if len(calls) == 1:
            raise OSError(errno.EXDEV, "cross-device link")
        return real_replace(a, b)

    monkeypatch.setattr(os, "replace", replace)
    tmp = src(tmp_path, b"from another disk")
    result = storage.store(tmp, REL, "lec1.pdf")

    assert result.path.read_bytes() == b"from another disk"
    assert not tmp.exists()
    assert [p.name for p in (storage.root / REL).iterdir()] == ["lec1.pdf"]


def test_failed_copy_leaves_no_partial_file(storage, tmp_path, monkeypatch):
    storage.store(src(tmp_path, b"v1"), REL, "lec1.pdf")

    def exdev(a, b):
        raise OSError(errno.EXDEV, "cross-device link")

    def copy_half_then_fail(a, b):
        with open(b, "wb") as f:
            f.write(b"par")
        raise OSError(errno.ENOSPC, "disk full")

    monkeypatch.setattr(os, "replace", exdev)
    monkeypatch.setattr(shutil, "copyfile", copy_half_then_fail)
    tmp = src(tmp_path, b"v2 that never lands")
    with pytest.raises(OSError, match="disk full"):
        storage.store(tmp, REL, "lec1.pdf")

    assert [p.name for p in (storage.root / REL).iterdir()] == ["lec1.pdf"]
    assert (storage.root / REL / "lec1.pdf").read_bytes() == b"v1"
    assert tmp.exists()


def test_failed_rename_leaves_no_file(storage, tmp_path, monkeypatch):
    def fail(a, b):
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        storage.store(src(tmp_path, b"x"), REL, "lec1.pdf")
    assert storage.list(REL) == []


def test_list_missing_folder_is_empty(storage):
    assert storage.list("nope") == []


def test_health(storage, tmp_path):
    assert storage.health() is ProviderState.AVAILABLE
    blocked = tmp_path / "file"
    blocked.write_text("not a dir")
    assert LocalStorageBackend(blocked / "courses").health() is ProviderState.BROKEN
