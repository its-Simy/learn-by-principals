from __future__ import annotations

import hashlib
import itertools
from dataclasses import dataclass
from pathlib import Path

from core.providers.storage.base import FileMeta, StorageBackend, UploadResult

FOLDER_MIME = "application/vnd.google-apps.folder"


@dataclass
class Node:
    file_id: str
    name: str
    parent: str
    is_folder: bool
    content: bytes = b""
    revisions: int = 0


class FakeStorage(StorageBackend):
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self._ids = itertools.count(1)
        self.corrupt_uploads = False

    def ensure_folder(self, path: str) -> str:
        parent = "root"
        for part in [p for p in path.split("/") if p]:
            found = self._child(parent, part, folder=True)
            if found is None:
                found = self._new(part, parent, is_folder=True)
            parent = found.file_id
        return parent

    def upload(self, local: Path, folder_id: str, name: str) -> UploadResult:
        content = local.read_bytes()
        if self.corrupt_uploads:
            content += b"!"
        node = self._child(folder_id, name, folder=False)
        created = node is None
        if node is None:
            node = self._new(name, folder_id, is_folder=False)
        node.content = content
        node.revisions += 1
        return UploadResult(node.file_id, name, hashlib.md5(content).hexdigest(), created)

    def verify(self, file_id: str, expected_md5: str) -> bool:
        return hashlib.md5(self.nodes[file_id].content).hexdigest() == expected_md5

    def list(self, folder_id: str) -> list[FileMeta]:
        return [
            FileMeta(
                n.file_id,
                n.name,
                FOLDER_MIME if n.is_folder else "application/octet-stream",
                None if n.is_folder else len(n.content),
                None if n.is_folder else hashlib.md5(n.content).hexdigest(),
            )
            for n in self.nodes.values()
            if n.parent == folder_id
        ]

    def path_of(self, file_id: str) -> str:
        parts: list[str] = []
        while file_id != "root":
            node = self.nodes[file_id]
            parts.append(node.name)
            file_id = node.parent
        return "/".join(reversed(parts))

    def files(self) -> dict[str, Node]:
        """Every non-folder node keyed by its full path."""
        return {self.path_of(n.file_id): n for n in self.nodes.values() if not n.is_folder}

    def _child(self, parent: str, name: str, folder: bool) -> Node | None:
        for n in self.nodes.values():
            if n.parent == parent and n.name == name and n.is_folder == folder:
                return n
        return None

    def _new(self, name: str, parent: str, is_folder: bool) -> Node:
        node = Node(f"id{next(self._ids)}", name, parent, is_folder)
        self.nodes[node.file_id] = node
        return node
