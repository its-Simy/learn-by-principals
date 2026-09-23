"""Playwright-held Brightspace browser session.

A persistent Chromium profile keeps Duo's remember-device cookie. D2L's session cookies do not
survive a browser restart, so after each successful login the context's storage state is saved to
``storage_state.json`` and its cookies are re-applied to every new headless context.

Sign-in is always manual: the tool opens a window, the user logs in and approves Duo, and the
run continues headless. The tool never sees the password.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, Playwright, sync_playwright

log = logging.getLogger(__name__)

WHOAMI_PATH = "/d2l/api/lp/1.0/users/whoami"
LOGIN_PATH = "/d2l/login"


@dataclass(frozen=True)
class HttpResponse:
    status: int
    url: str
    headers: dict[str, str] = field(default_factory=dict)  # lowercased keys
    body: bytes = b""

    def json(self) -> Any:
        return json.loads(self.body)


class Session(Protocol):
    base_url: str

    def get(self, path: str) -> HttpResponse: ...

    def whoami_ok(self) -> bool: ...

    def login(self) -> None:
        """Open a visible window and block until the user has logged in (Duo included)."""

    def close(self) -> None: ...


def chromium_executable() -> Path | None:
    """Playwright's Chromium binary, or None when ``playwright install chromium`` hasn't run."""
    with sync_playwright() as pw:
        path = Path(pw.chromium.executable_path)
    return path if path.exists() else None


def on_site(url: str, base_url: str) -> bool:
    """True when ``url`` is on the Brightspace host and not its login page."""
    target, base = urlsplit(url), urlsplit(base_url)
    return target.netloc == base.netloc and not target.path.startswith(LOGIN_PATH)


def is_whoami_ok(resp: HttpResponse, base_url: str) -> bool:
    return (
        resp.status == 200
        and on_site(resp.url, base_url)
        and "json" in resp.headers.get("content-type", "")
    )


class PlaywrightSession:
    def __init__(
        self,
        base_url: str,
        profile_dir: Path,
        storage_state_path: Path,
        login_timeout_s: int = 600,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._profile_dir = profile_dir
        self._storage_state_path = storage_state_path
        self._login_timeout_s = login_timeout_s
        self._pw: Playwright | None = None
        self._context: BrowserContext | None = None

    def get(self, path: str) -> HttpResponse:
        context = self._context or self._launch(headless=True)
        resp = context.request.get(self.base_url + path, fail_on_status_code=False)
        try:
            return HttpResponse(
                status=resp.status,
                url=resp.url,
                headers={k.lower(): v for k, v in resp.headers.items()},
                body=resp.body(),
            )
        finally:
            resp.dispose()

    def whoami_ok(self) -> bool:
        return is_whoami_ok(self.get(WHOAMI_PATH), self.base_url)

    def login(self) -> None:
        self._close_context()
        context = self._launch(headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(self.base_url + "/d2l/home")
        log.warning("Log in to Brightspace and approve Duo in the browser window.")
        deadline = time.monotonic() + self._login_timeout_s
        while time.monotonic() < deadline:
            if self.whoami_ok():
                self._save_storage_state(context)
                log.info("Brightspace login complete.")
                self._close_context()
                return
            page.wait_for_timeout(2000)
        self._close_context()
        raise TimeoutError(f"Brightspace login not completed within {self._login_timeout_s}s")

    def close(self) -> None:
        self._close_context()
        if self._pw is not None:
            self._pw.stop()
            self._pw = None

    def _launch(self, headless: bool) -> BrowserContext:
        if self._pw is None:
            self._pw = sync_playwright().start()
        self._profile_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        context = self._pw.chromium.launch_persistent_context(
            str(self._profile_dir), headless=headless
        )
        if self._storage_state_path.exists():
            cookies = json.loads(self._storage_state_path.read_text()).get("cookies", [])
            if cookies:
                context.add_cookies(cookies)
        self._context = context
        return context

    def _save_storage_state(self, context: BrowserContext) -> None:
        context.storage_state(path=str(self._storage_state_path))
        self._storage_state_path.chmod(0o600)

    def _close_context(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
