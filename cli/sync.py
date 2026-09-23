from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from cli import common
from core.config import ensure_home, load_config
from core.memory.db import Manifest, connect
from core.providers.storage.local import LocalStorageBackend
from core.sync.engine import SyncEngine, SyncReport, select_courses
from core.sync.link import LinkReport, LinkStep

console = Console()


def sync(
    course: str | None = typer.Option(None, help="Only this course code (CSE220) or org unit id."),
    all_courses: bool = typer.Option(False, "--all", help="Every active course offering."),
    term: str | None = typer.Option(None, help="Term folder, e.g. Fall-2026. Default: from date."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report what would change; write nothing."
    ),
    force: bool = typer.Option(
        False, "--force", help="Re-download files the manifest says are current."
    ),
    no_link: bool = typer.Option(False, "--no-link", help="Skip the NotebookLM link step."),
    include_code: bool = typer.Option(
        False, "--include-code", help="Also send the code and other buckets to NotebookLM."
    ),
) -> None:
    """Copy new or changed Brightspace files into the local course folder."""
    if (course is None) == (not all_courses):
        raise typer.BadParameter("Pass exactly one of --course or --all.")
    config = load_config(term=term)
    ensure_home(config)
    conn = connect(config.db_path)
    reports: list[SyncReport] = []
    links: list[LinkReport] = []
    db = Manifest(conn)
    try:
        with common.open_lms(config) as lms:
            lms.ensure_session()
            courses = select_courses(lms.list_courses(), course)
            if not courses:
                raise typer.BadParameter(f"No active Brightspace course matches {course!r}.")
            engine = SyncEngine(lms, LocalStorageBackend(config.storage_root), db, config)
            for c in courses:
                reports.append(engine.sync_course(c, config.term, dry_run=dry_run, force=force))
        if not (dry_run or no_link):
            with common.open_knowledge(config, conn) as knowledge:
                step = LinkStep(knowledge, db, config.nlm_source_cap, include_code)
                links = [step.run(r.course) for r in reports]
    finally:
        conn.close()

    print_reports(reports, config.term, dry_run)
    print_links(links)
    if any(r.failures for r in reports) or any(r.failures for r in links):
        raise typer.Exit(1)


def print_reports(reports: list[SyncReport], term: str, dry_run: bool) -> None:
    title = f"Sync {term}" + (" (dry run: nothing written)" if dry_run else "")
    table = Table("Course", "New", "Changed", "Skipped", "Links", "Failed", title=title)
    for r in reports:
        failed = f"[red]{r.failed}[/]" if r.failed else "0"
        table.add_row(r.course, str(r.new), str(r.changed), str(r.skipped), str(r.links), failed)
    console.print(table)
    for r in reports:
        for failure in r.failures:
            console.print(f"[red]{r.course}: {failure}[/]")


def print_links(reports: list[LinkReport]) -> None:
    if not reports:
        return
    table = Table("Course", "Added", "Replaced", "Deferred", "Failed", title="NotebookLM")
    for r in reports:
        failed = f"[red]{r.failed}[/]" if r.failed else "0"
        table.add_row(r.course, str(r.added), str(r.replaced), str(r.deferred), failed)
    console.print(table)
    for r in reports:
        for failure in r.failures:
            console.print(f"[red]{r.course} NotebookLM: {failure}[/]")
