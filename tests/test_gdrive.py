"""GoogleDriveBackend against googleapiclient's offline HTTP mocks; no network."""

import json
from urllib.parse import parse_qs, urlsplit

from googleapiclient.discovery import build
from googleapiclient.http import HttpMockSequence

from core.providers.storage.gdrive import GoogleDriveBackend, _quote


class RecordingHttp(HttpMockSequence):
    def __init__(self, responses):
        super().__init__(responses)
        self.calls: list[tuple[str, str]] = []

    def request(self, uri, method="GET", body=None, headers=None, **kwargs):
        self.calls.append((method, uri))
        return super().request(uri, method, body, headers, **kwargs)


def ok(payload: dict) -> tuple[dict, str]:
    return {"status": "200"}, json.dumps(payload)


def backend(responses) -> tuple[GoogleDriveBackend, RecordingHttp]:
    http = RecordingHttp(responses)
    return GoogleDriveBackend(build("drive", "v3", http=http, static_discovery=True)), http


def query(uri: str) -> str:
    return parse_qs(urlsplit(uri).query)["q"][0]


def test_ensure_folder_creates_missing_segments_and_caches():
    drive, http = backend(
        [
            ok({"files": []}),
            ok({"id": "f1"}),
            ok({"files": [{"id": "f2"}]}),
        ]
    )
    assert drive.ensure_folder("BrightLearn/2026-Fall") == "f2"
    assert drive.ensure_folder("BrightLearn/2026-Fall/") == "f2"

    assert [m for m, _ in http.calls] == ["GET", "POST", "GET"]
    assert query(http.calls[0][1]) == (
        "name = 'BrightLearn' and 'root' in parents"
        " and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    assert "'f1' in parents" in query(http.calls[2][1])


def test_upload_creates_new_file_with_resumable_upload(tmp_path):
    local = tmp_path / "x"
    local.write_bytes(b"%PDF-1.7")
    drive, http = backend(
        [
            ok({"files": []}),
            ({"status": "200", "location": "https://upload.example/session"}, ""),
            ok({"id": "d1", "name": "lec1.pdf", "md5Checksum": "abc"}),
        ]
    )
    result = drive.upload(local, "f2", "lec1.pdf")

    assert result.file_id == "d1"
    assert result.created is True
    assert "mimeType != 'application/vnd.google-apps.folder'" in query(http.calls[0][1])
    assert http.calls[1][0] == "POST"
    assert "uploadType=resumable" in http.calls[1][1]
    assert "keepRevisionForever=true" in http.calls[1][1]


def test_upload_updates_existing_file_in_place(tmp_path):
    local = tmp_path / "x"
    local.write_bytes(b"%PDF-1.7 v2")
    drive, http = backend(
        [
            ok({"files": [{"id": "d1"}]}),
            ({"status": "200", "location": "https://upload.example/session"}, ""),
            ok({"id": "d1", "name": "lec1.pdf", "md5Checksum": "def"}),
        ]
    )
    result = drive.upload(local, "f2", "lec1.pdf")

    assert result.file_id == "d1"
    assert result.created is False
    assert http.calls[1][0] == "PATCH"
    assert "/files/d1" in http.calls[1][1]
    assert "keepRevisionForever=true" in http.calls[1][1]


def test_verify_compares_md5():
    drive, _ = backend([ok({"md5Checksum": "abc"}), ok({"md5Checksum": "abc"})])
    assert drive.verify("d1", "abc") is True
    assert drive.verify("d1", "zzz") is False


def test_list_follows_pages():
    drive, _ = backend(
        [
            ok({"nextPageToken": "p2", "files": [{"id": "a", "name": "a.pdf", "size": "3"}]}),
            ok(
                {
                    "files": [
                        {"id": "b", "name": "b", "mimeType": "application/vnd.google-apps.folder"}
                    ]
                }
            ),
        ]
    )
    items = drive.list("f2")
    assert [(i.file_id, i.size, i.is_folder) for i in items] == [("a", 3, False), ("b", None, True)]


def test_quote_escapes_drive_query_literals():
    assert _quote("Bob's \\ notes") == "Bob\\'s \\\\ notes"
