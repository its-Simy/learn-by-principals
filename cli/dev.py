"""Developer helpers for inspecting live Brightspace data."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from core.config import ensure_home, load_config
from core.providers.lms.brightspace import BrightspaceSessionProvider
from core.providers.lms.session import PlaywrightSession

app = typer.Typer(no_args_is_help=True, help="Developer helpers.")
console = Console()


@app.command()
def courses() -> None:
    """List active course offerings with the code BrightLearn derives for folders."""
    config = load_config()
    ensure_home(config)
    session = PlaywrightSession(
        config.brightspace_base_url,
        config.browser_profile_dir,
        config.storage_state_path,
        config.login_timeout_s,
    )
    try:
        lms = BrightspaceSessionProvider(session)
        lms.ensure_session()
        table = Table("Org unit", "Code (folder)", "Name")
        for c in lms.list_courses():
            table.add_row(str(c.org_unit_id), c.code, c.name)
    finally:
        session.close()
    console.print(table)
