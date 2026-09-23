"""Brightspace via session-cookie ``/d2l/api`` calls. DOM scraping is a later fallback only."""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import re
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from core.providers.lms.base import Course, DownloadResult, LMSError, LMSProvider, Resource
from core.providers.lms.session import HttpResponse, Session, on_site
from core.providers.state import ProviderState

log = logging.getLogger(__name__)

VERSIONS_PATH = "/d2l/api/versions/"
ENROLLMENTS_PATH = "/d2l/api/lp/1.0/enrollments/myenrollments/"
COURSE_OFFERING_TYPE_ID = 3
MODULE_SEPARATOR = " / "

_COURSE_CODE_RE = re.compile(r"\b([A-Z]{2,4})[\s_-]?(\d{3})\b")


def course_code(org_unit: dict[str, Any]) -> str:
    """``CSE220`` from an org unit's Code or Name; falls back to the raw Code."""
    for field in ("Code", "Name"):
        match = _COURSE_CODE_RE.search(org_unit.get(field) or "")
        if match:
            return match.group(1) + match.group(2)
    return safe_name(org_unit.get("Code") or str(org_unit["Id"]))


def safe_name(name: str) -> str:
    """Strip path separators and control characters from a server-supplied name."""
    name = re.sub(r"[\x00-\x1f/\\]", "_", name).strip()
    return name or "untitled"


def filename_from_disposition(header: str | None) -> str | None:
    if not header:
        return None
    msg = Message()
    msg["content-disposition"] = header
    name = msg.get_filename()
    return safe_name(name) if name else None


def flatten_toc(toc: dict[str, Any], org_unit_id: int) -> list[Resource]:
    resources: list[Resource] = []

    def walk(modules: list[dict[str, Any]], parents: list[str]) -> None:
        for module in modules:
            path = [*parents, module.get("Title", "")]
            for topic in module.get("Topics", []):
                resources.append(
                    Resource(
                        org_unit_id=org_unit_id,
                        topic_id=int(topic["TopicId"]),
                        module_path=MODULE_SEPARATOR.join(path),
                        title=topic.get("Title", ""),
                        type_identifier=topic.get("TypeIdentifier", ""),
                        url=topic.get("Url"),
                        last_modified=topic.get("LastModifiedDate"),
                    )
                )
            walk(module.get("Modules", []), path)

    walk(toc.get("Modules", []), [])
    return resources


class BrightspaceSessionProvider(LMSProvider):
    def __init__(self, session: Session) -> None:
        self._session = session
        self._le_version: str | None = None

    def ensure_session(self) -> None:
        if self._session.whoami_ok():
            return
        log.info("Brightspace session not valid; opening headed login.")
        self._session.login()
        if not self._session.whoami_ok():
            raise LMSError("Brightspace login did not produce a valid session")

    def health(self) -> ProviderState:
        """Cheap synthetic check (``whoami``); never opens a login window."""
        try:
            ok = self._session.whoami_ok()
        except Exception:
            log.exception("Brightspace health check failed")
            return ProviderState.BROKEN
        return ProviderState.AVAILABLE if ok else ProviderState.AUTH_EXPIRED

    def le_version(self) -> str:
        if self._le_version is None:
            products = self._get(VERSIONS_PATH).json()
            le = next((p for p in products if p.get("ProductCode") == "le"), None)
            if le is None:
                raise LMSError("Brightspace /versions/ has no 'le' product")
            self._le_version = le["LatestVersion"]
        return self._le_version

    def list_courses(self) -> list[Course]:
        courses: list[Course] = []
        bookmark: str | None = None
        while True:
            params: dict[str, Any] = {"orgUnitTypeId": COURSE_OFFERING_TYPE_ID}
            if bookmark:
                params["bookmark"] = bookmark
            page = self._get(f"{ENROLLMENTS_PATH}?{urlencode(params)}").json()
            for item in page.get("Items", []):
                org_unit, access = item["OrgUnit"], item.get("Access", {})
                if org_unit.get("Type", {}).get("Id") != COURSE_OFFERING_TYPE_ID:
                    continue
                if not (access.get("IsActive") and access.get("CanAccess")):
                    continue
                courses.append(
                    Course(
                        org_unit_id=int(org_unit["Id"]),
                        code=course_code(org_unit),
                        name=org_unit.get("Name", ""),
                    )
                )
            paging = page.get("PagingInfo") or {}
            if not paging.get("HasMoreItems"):
                return courses
            bookmark = paging.get("Bookmark")

    def list_resources(self, org_unit_id: int) -> list[Resource]:
        toc = self._get(f"/d2l/api/le/{self.le_version()}/{org_unit_id}/content/toc").json()
        return flatten_toc(toc, org_unit_id)

    def download(self, resource: Resource, dest: Path) -> DownloadResult:
        path = (
            f"/d2l/api/le/{self.le_version()}/{resource.org_unit_id}"
            f"/content/topics/{resource.topic_id}/file"
        )
        resp = self._get(path)
        content_type = resp.headers.get("content-type")
        filename = filename_from_disposition(resp.headers.get("content-disposition"))
        if filename is None:
            ext = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ""
            filename = safe_name(resource.title) + ext
            log.warning(
                "Topic %s has no Content-Disposition; using %r", resource.topic_id, filename
            )
        dest.write_bytes(resp.body)
        return DownloadResult(
            path=dest,
            filename=filename,
            size=len(resp.body),
            md5=hashlib.md5(resp.body).hexdigest(),
            content_type=content_type,
        )

    def _get(self, path: str) -> HttpResponse:
        """GET with one re-login if the session expired mid-run."""
        for attempt in (1, 2):
            resp = self._session.get(path)
            if resp.status == 200 and on_site(resp.url, self._session.base_url):
                return resp
            if self._session.whoami_ok():
                if resp.status == 200:  # off-host 200 with a live session: a legitimate redirect
                    return resp
                raise LMSError(f"GET {path} -> HTTP {resp.status}")
            if attempt == 1:
                log.warning("Brightspace session expired mid-run; pausing for login.")
                self._session.login()
        raise LMSError(f"GET {path} failed after re-login (HTTP {resp.status})")
