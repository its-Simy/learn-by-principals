"""``brightlearn web`` (alias ``start``): the API and the web app on one localhost port (BL-044).

Before serving it checks what a double-click would otherwise discover the hard way: the web app
is built, nothing else holds the port, and an already running BrightLearn is simply opened.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import typer
from rich.console import Console

console = Console()

BUILD_CMD = "pnpm --dir web install --frozen-lockfile && pnpm --dir web build"
READY_TIMEOUT_S = 30.0


def dist_ready() -> bool:
    from api.static import DIST  # here, so the other commands don't import the web stack

    return (DIST / "index.html").is_file()


def already_running(url: str) -> bool:
    """Whether a BrightLearn answers at ``url`` (its health has a ``schema_version``)."""
    try:
        with urllib.request.urlopen(f"{url}api/health", timeout=1) as resp:
            return "schema_version" in json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return False


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def wait_until_ready(url: str, timeout_s: float = READY_TIMEOUT_S) -> bool:
    """Poll the health route until the server answers (uvicorn runs the lifespan first, so the
    first answer means the workers are up too)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if already_running(url):
            return True
        time.sleep(0.25)
    return False


def open_when_ready(url: str) -> None:
    if wait_until_ready(url):
        webbrowser.open(url)
    else:
        console.print(f"Not answering after {READY_TIMEOUT_S:.0f} s; open {url} yourself.")


def start_opener(url: str) -> None:
    thread = threading.Thread(target=open_when_ready, args=(url,), daemon=True)
    thread.start()


def web(
    port: int = typer.Option(8765, help="Port on 127.0.0.1."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open it in the browser."),
) -> None:
    """Serve the web app on 127.0.0.1 only: there is no login."""
    url = f"http://127.0.0.1:{port}/"
    if not dist_ready():
        if open_browser:
            console.print(f"[red]The web app isn't built.[/] Run: {BUILD_CMD}")
            raise typer.Exit(1)
        console.print("[yellow]The web app isn't built; serving the API only.[/]")
    if already_running(url):
        console.print(f"BrightLearn is already running on {url}")
        if open_browser:
            webbrowser.open(url)
        return
    if not port_free(port):
        console.print(
            f"[red]Port {port} is in use by another program.[/] "
            f"Try `brightlearn start --port {port + 1}`."
        )
        raise typer.Exit(1)

    import uvicorn  # here, so the other commands don't pay for importing the web stack

    if open_browser:
        start_opener(url)
    console.print(f"BrightLearn on {url} (Ctrl-C stops it)")
    # Without a timeout, uvicorn waits for every open request before the lifespan's
    # engine.close(), and one waiting on a tutor turn can take minutes. After two seconds it
    # moves on, and close() fails whatever the workers are still running (P98).
    uvicorn.run(
        "api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        log_config=None,
        timeout_graceful_shutdown=2,
    )
