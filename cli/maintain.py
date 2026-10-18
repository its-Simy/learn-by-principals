"""``brightlearn maintain``, and the once-a-day automatic run every other command triggers."""

from __future__ import annotations

import logging

from rich.console import Console
from rich.table import Table

from core.config import Config, load_config
from core.maintenance import MaintenanceReport, maintain, maybe_maintain
from core.memory.db import connect

log = logging.getLogger(__name__)
console = Console()

# Read-only by contract (doctor, setup), this command itself, and the developer helpers: `dev
# openapi` is run from scripts and must never open, let alone migrate, the real database (P102).
NO_AUTO_RUN = frozenset({"maintain", "doctor", "dev", "setup"})


def maintain_cmd() -> None:
    """Decay retention, archive sessions older than 30 days, and say what changed."""
    config = load_config()
    conn = connect(config.db_path)
    try:
        report = maintain(conn, config.vault_root, half_life_days=config.retention_half_life_days)
    finally:
        conn.close()
    print_report(report)


def print_report(report: MaintenanceReport) -> None:
    if report.decayed:
        table = Table("Concept", "Retention", "Days since evidence", title="Retention decayed")
        for c in sorted(report.decayed, key=lambda c: c.new):
            old = "—" if c.old is None else f"{c.old:.2f}"
            table.add_row(c.concept_id, f"{old} → {c.new:.2f}", f"{c.days_since_evidence:.0f}")
        console.print(table)
    else:
        console.print("Retention: nothing changed.")
    if report.closed:
        console.print(
            f"Closed {len(report.closed)} session(s) idle over 24 hours (not analyzed): "
            + ", ".join(report.closed)
        )
    if report.archived:
        console.print(f"Archived {len(report.archived)} session(s): {', '.join(report.archived)}")
    else:
        console.print("Sessions: nothing old enough to archive.")


def auto_maintain(command: str | None, config: Config | None = None) -> None:
    """Run maintenance first if it hasn't run in 24 hours. Never blocks the command."""
    if command in NO_AUTO_RUN:
        return
    try:
        config = config or load_config()
        if not config.db_path.exists():
            return  # nothing to maintain; don't create the database just for this
        conn = connect(config.db_path)
        try:
            report = maybe_maintain(conn, config.vault_root, config.retention_half_life_days)
        finally:
            conn.close()
    except Exception:
        log.warning("Automatic maintenance failed; run `brightlearn maintain`", exc_info=True)
        return
    if report is not None and (report.decayed or report.archived or report.closed):
        log.info(
            "Daily maintenance: %d retention value(s) decayed, %d idle session(s) closed,"
            " %d session(s) archived",
            len(report.decayed),
            len(report.closed),
            len(report.archived),
        )
