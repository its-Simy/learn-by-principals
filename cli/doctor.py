"""``brightlearn doctor``: every check is read-only (``core.doctor``)."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from core.config import load_config
from core.doctor import Status, run_checks

console = Console()

COLOURS = {Status.OK: "green", Status.WARN: "yellow", Status.FAIL: "red", Status.OFF: "grey50"}


def doctor() -> None:
    """Report every provider's health. Every check is read-only."""
    results = run_checks(load_config())
    table = Table("Check", "Status", "Detail")
    for c in results:
        colour = COLOURS[c.status]
        table.add_row(
            f"[{colour}]{c.name}[/]", f"[{colour}]{c.status}[/]", f"[{colour}]{escape(c.detail)}[/]"
        )
    console.print(table)
    if any(c.status is Status.FAIL for c in results):
        raise typer.Exit(1)
