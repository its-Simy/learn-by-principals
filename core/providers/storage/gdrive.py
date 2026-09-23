"""Google Drive REST v3 backend (OAuth desktop client)."""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from core.config import Config, ensure_home
from core.providers.state import ProviderState
from core.providers.storage.base import FileMeta, StorageBackend, StorageError, UploadResult

log = logging.getLogger(__name__)

# drive.file: the app sees only files it created. Enough for sync, verify and list.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
FOLDER_MIME = "application/vnd.google-apps.folder"
FILE_FIELDS = "id, name, mimeType, size, md5Checksum"


class DriveAuthRequired(StorageError):
    pass


def load_credentials(config: Config, interactive: bool) -> Credentials:
    creds: Credentials | None = None
    if config.drive_token_path.exists():
        creds = Credentials.from_authorized_user_file(str(config.drive_token_path), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            creds = None
    if not (creds and creds.valid):
        if not interactive:
            raise DriveAuthRequired("Drive is not authorized; run `brightlearn sync` once")
        if not config.drive_client_secret_path.exists():
            raise DriveAuthRequired(
                f"Missing OAuth client secret at {config.drive_client_secret_path}"
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(config.drive_client_secret_path), SCOPES
        )
        creds = flow.run_local_server(port=0)
    ensure_home(config)
    config.drive_token_path.write_text(creds.to_json())
    config.drive_token_path.chmod(0o600)
    return creds


def _quote(value: str) -> str:
    """Escape a literal for a Drive ``q`` expression."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _file_meta(item: dict[str, Any]) -> FileMeta:
    return FileMeta(
        file_id=item["id"],
        name=item["name"],
        mime_type=item.get("mimeType", ""),
        size=int(item["size"]) if "size" in item else None,
        md5=item.get("md5Checksum"),
    )


class GoogleDriveBackend(StorageBackend):
    def __init__(self, service: Any) -> None:
        self._svc = service
        self._folders: dict[tuple[str, str], str] = {}

    @classmethod
    def from_config(cls, config: Config, interactive: bool = True) -> GoogleDriveBackend:
        creds = load_credentials(config, interactive=interactive)
        return cls(build("drive", "v3", credentials=creds, cache_discovery=False))

    def health(self) -> ProviderState:
        try:
            self._svc.files().list(pageSize=1, fields="files(id)").execute()
        except Exception:
            log.exception("Drive health check failed")
            return ProviderState.BROKEN
        return ProviderState.AVAILABLE

    def ensure_folder(self, path: str) -> str:
        parent = "root"
        for part in [p for p in path.split("/") if p]:
            parent = self._child_folder(parent, part)
        return parent

    def upload(self, local: Path, folder_id: str, name: str) -> UploadResult:
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        media = MediaFileUpload(str(local), mimetype=mime, resumable=local.stat().st_size > 0)
        existing = self._find(folder_id, name, folder=False)
        files = self._svc.files()
        # keepRevisionForever: a replaced version would otherwise be purged after 30 days.
        common = {"media_body": media, "fields": FILE_FIELDS, "keepRevisionForever": True}
        if existing:
            request = files.update(fileId=existing, **common)
        else:
            request = files.create(body={"name": name, "parents": [folder_id]}, **common)
        response = None
        if media.resumable():
            while response is None:
                _, response = request.next_chunk()
        else:
            response = request.execute()
        return UploadResult(
            file_id=response["id"],
            name=response["name"],
            md5=response.get("md5Checksum"),
            created=existing is None,
        )

    def verify(self, file_id: str, expected_md5: str) -> bool:
        meta = self._svc.files().get(fileId=file_id, fields="md5Checksum").execute()
        return meta.get("md5Checksum") == expected_md5

    def list(self, folder_id: str) -> list[FileMeta]:
        items: list[FileMeta] = []
        token: str | None = None
        while True:
            resp = (
                self._svc.files()
                .list(
                    q=f"'{_quote(folder_id)}' in parents and trashed = false",
                    fields=f"nextPageToken, files({FILE_FIELDS})",
                    pageSize=100,
                    pageToken=token,
                )
                .execute()
            )
            items.extend(_file_meta(f) for f in resp.get("files", []))
            token = resp.get("nextPageToken")
            if not token:
                return items

    def _child_folder(self, parent: str, name: str) -> str:
        key = (parent, name)
        if key not in self._folders:
            folder_id = self._find(parent, name, folder=True)
            if folder_id is None:
                body = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent]}
                folder_id = self._svc.files().create(body=body, fields="id").execute()["id"]
                log.info("Created Drive folder %r", name)
            self._folders[key] = folder_id
        return self._folders[key]

    def _find(self, parent: str, name: str, folder: bool) -> str | None:
        op = "=" if folder else "!="
        q = (
            f"name = '{_quote(name)}' and '{_quote(parent)}' in parents"
            f" and mimeType {op} '{FOLDER_MIME}' and trashed = false"
        )
        resp = self._svc.files().list(q=q, fields="files(id)", pageSize=2).execute()
        found = resp.get("files", [])
        if len(found) > 1:
            log.warning("Multiple Drive items named %r in %s; using the first", name, parent)
        return found[0]["id"] if found else None
