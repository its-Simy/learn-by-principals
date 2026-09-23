from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from core.config import ensure_home, load_config
from core.memory.db import Manifest, connect
from core.providers.lms.brightspace import BrightspaceSessionProvider
from core.providers.lms.session import PlaywrightSession
from core.providers.storage.gdrive import GoogleDriveBackend
from core.sync.engine import SyncEngine

console = Console()


def sync(
    course: str | None = typer.Option(None, help="Only this course code (CSE220) or org unit id."),
    term: str | None = typer.Option(None, help="Drive term folder, e.g. 2026-Fall."),
) -> None:
    """Copy new or changed Brightspace files into Google Drive."""
    config = load_config(term=term)
    ensure_home(config)
    conn = connect(config.db_path)
    session = PlaywrightSession(
        config.brightspace_base_url,
        config.browser_profile_dir,
        config.storage_state_path,
        config.login_timeout_s,
    )
    try:
        storage = GoogleDriveBackend.from_config(config)
        engine = SyncEngine(BrightspaceSessionProvider(session), storage, Manifest(conn), config)
        report = engine.run(course=course)
    finally:
        session.close()
        conn.close()

    table = Table("Courses", "Seen", "Uploaded", "Unchanged", "Links", "Failed")
    table.add_row(
        ", ".join(report.courses) or "-",
        str(report.seen),
        str(report.uploaded),
        str(report.unchanged),
        str(report.links),
        str(report.failed),
    )
    console.print(table)
    for error in report.errors:
        console.print(f"[red]{error}[/]")
    if report.errors:
        raise typer.Exit(1)
