"""``brightlearn dashboard``: write the usage page and open it (BL-037)."""

from __future__ import annotations

import webbrowser

import typer
from rich.console import Console

from core.config import ensure_home, load_config
from core.memory.db import connect
from dashboard.data import collect
from dashboard.render import render

console = Console()


def dashboard(
    open_page: bool = typer.Option(True, "--open/--no-open", help="Open it in the browser."),
) -> None:
    """Write ~/.brightlearn/dashboard.html (self-contained) from the local database."""
    config = load_config()
    ensure_home(config)
    conn = connect(config.db_path)
    try:
        html = render(collect(conn))
    finally:
        conn.close()
    path = config.home / "dashboard.html"
    path.write_text(html, encoding="utf-8")
    console.print(f"Dashboard -> {path}")
    if open_page:
        webbrowser.open(path.as_uri())
