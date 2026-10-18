"""The Playwright tour's harness: dev servers on the fakes, and the browser wiring.

Each test module gets one fresh ``scripts/dev_server.py`` (its own scratch home, a free port,
``--delay 0``), so a module's tests share its state and no module sees another's. The browser
opens a fresh context per test with ``base_url`` set to that server, so tests use relative URLs.
See tests/e2e/README.md for how to run the tour and read a failure's trace.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import BrowserContext, Playwright, expect

from tests.e2e.helpers import DevServer

ROOT = Path(__file__).resolve().parents[2]
DEV_SERVER = ROOT / "scripts" / "dev_server.py"
WEB_BUILD = ROOT / "web" / "dist" / "index.html"
START_TIMEOUT_S = 30.0
PORT_ATTEMPTS = 3

# Assertions wait this long for the UI; the jobs poll every 2 s, so an end state can take a few.
expect.set_options(timeout=10_000)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _log_tail(log: Path, lines: int = 40) -> str:
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(no log)"
    return "\n".join(text.splitlines()[-lines:])


def _healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=2) as response:
            return json.load(response).get("ok") is True
    except (OSError, urllib.error.URLError, ValueError):
        return False


def _server_env() -> dict[str, str]:
    """This environment minus any BRIGHTLEARN_* setting (the dev server sets its own home)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("BRIGHTLEARN_")}
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _launch(base: Path, port: int, no_models: bool) -> DevServer:
    """Starts one server on ``port`` and waits for its health route. Raises ``OSError`` if the
    port was taken meanwhile, and fails the test with the log's tail for any other exit."""
    home, log = base / "home", base / "server.log"
    command = [sys.executable, str(DEV_SERVER), "--home", str(home), "--port", str(port)]
    command += ["--delay", "0"] + (["--no-models"] if no_models else [])
    with log.open("ab") as out:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=_server_env(),
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
        )
    server = DevServer(f"http://127.0.0.1:{port}", home, log, process)
    deadline = time.monotonic() + START_TIMEOUT_S
    while time.monotonic() < deadline:
        if process.poll() is not None:
            tail = _log_tail(log)
            if "address already in use" in tail.lower():
                raise OSError(f"port {port} is in use")
            pytest.fail(f"dev server exited with {process.returncode}:\n{tail}", pytrace=False)
        if _healthy(server.url):
            return server
        time.sleep(0.2)
    server.stop()
    pytest.fail(f"dev server not healthy after {START_TIMEOUT_S:.0f} s:\n{_log_tail(log)}")


@pytest.fixture(scope="session")
def dev_server_factory(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Callable[..., DevServer]]:
    """``start(no_models=False)`` starts a fresh dev server; every one is stopped at the end."""
    started: list[DevServer] = []

    def start(*, no_models: bool = False) -> DevServer:
        base = tmp_path_factory.mktemp("dev-server")
        for attempt in range(PORT_ATTEMPTS):
            try:
                server = _launch(base, _free_port(), no_models)
            except OSError:
                if attempt == PORT_ATTEMPTS - 1:
                    raise
                continue
            started.append(server)
            return server
        raise AssertionError("unreachable")

    yield start
    for server in started:
        server.stop()


@pytest.fixture(scope="module")
def server(dev_server_factory: Callable[..., DevServer]) -> Iterator[DevServer]:
    """One fresh server (fresh home, CSE220 seeded) per test module."""
    started = dev_server_factory()
    yield started
    started.stop()


# -- Playwright wiring ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def browser_type_launch_args(
    browser_type_launch_args: dict[str, Any], playwright: Playwright, browser_name: str
) -> dict[str, Any]:
    """The plugin's options, plus the installed Chrome when Playwright's own Chromium isn't
    downloaded; ``BRIGHTLEARN_E2E_CHANNEL`` forces a channel."""
    args = dict(browser_type_launch_args)
    forced = os.environ.get("BRIGHTLEARN_E2E_CHANNEL")
    if forced:
        args["channel"] = forced
    elif (
        "channel" not in args
        and browser_name == "chromium"
        and not Path(playwright.chromium.executable_path).exists()
    ):
        args["channel"] = "chrome"
    return args


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict[str, Any]) -> dict[str, Any]:
    """A desktop window in a fixed locale and timezone; ``base_url`` comes from ``context``."""
    args = {k: v for k, v in browser_context_args.items() if k != "base_url"}
    return {
        **args,
        "viewport": {"width": 1400, "height": 900},
        "locale": "en-US",
        "timezone_id": "America/New_York",
    }


@pytest.fixture
def context(new_context: Callable[..., BrowserContext], server: DevServer) -> BrowserContext:
    """The plugin's context (tracing and screenshots included) on this module's server."""
    return new_context(base_url=server.url)


# -- preconditions and failure artifacts -------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _web_app_built() -> None:
    """The dev server serves web/dist; without a build there is nothing to drive."""
    if WEB_BUILD.exists():
        return
    message = "web/dist/index.html is missing: run `pnpm --dir web build` first"
    if os.environ.get("CI"):
        pytest.fail(message, pytrace=False)
    pytest.skip(message)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):
    """Keeps each phase's report on the item (``rep_setup``, ``rep_call``) for the fixture below."""
    report = yield
    setattr(item, f"rep_{report.when}", report)
    return report


@pytest.fixture(autouse=True)
def _server_log_on_failure(request: pytest.FixtureRequest, output_path: str) -> Iterator[None]:
    """A failed test's folder under test-results/ gets the server's log beside its trace."""
    yield
    reports = (getattr(request.node, f"rep_{when}", None) for when in ("setup", "call"))
    if not any(report is not None and report.failed for report in reports):
        return
    started = request.node.funcargs.get("server")
    if isinstance(started, DevServer) and started.log.exists():
        os.makedirs(output_path, exist_ok=True)
        shutil.copyfile(started.log, Path(output_path) / "server.log")
