"""Developer helpers for inspecting live Brightspace data."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from cli import common
from core.config import ensure_home, load_config

app = typer.Typer(no_args_is_help=True, help="Developer helpers.")
console = Console()


@app.command()
def courses() -> None:
    """List active course offerings with the code BrightLearn derives for folders."""
    config = load_config()
    ensure_home(config)
    with common.open_lms(config) as lms:
        lms.ensure_session()
        table = Table("Org unit", "Code (folder)", "Name")
        for c in lms.list_courses():
            table.add_row(str(c.org_unit_id), c.code, c.name)
    console.print(table)
