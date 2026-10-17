"""``brightlearn web``: the API and the web app on one localhost port (BL-044)."""

from __future__ import annotations

import threading
import webbrowser

import typer
from rich.console import Console

console = Console()


def web(
    port: int = typer.Option(8765, help="Port on 127.0.0.1."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open it in the browser."),
) -> None:
    """Serve the web app on 127.0.0.1 only: there is no login."""
    import uvicorn  # here, so the other commands don't pay for importing the web stack

    url = f"http://127.0.0.1:{port}/"
    if open_browser:
        # After a second, so the server is listening by the time the page loads.
        timer = threading.Timer(1.0, webbrowser.open, args=(url,))
        timer.daemon = True
        timer.start()
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
