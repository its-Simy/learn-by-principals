from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from core import wiring
from core.config import ensure_home, load_config
from core.memory.db import Courses, Manifest, connect
from core.sync.link import LinkReport, LinkStep

console = Console()


def sync(
    course: str | None = typer.Option(None, help="Only this course code, e.g. CSE220."),
    all_courses: bool = typer.Option(False, "--all", help="Every course."),
    include_code: bool = typer.Option(
        False, "--include-code", help="Also send the code bucket to NotebookLM."
    ),
) -> None:
    """Push stored course files to NotebookLM."""
    if (course is None) == (not all_courses):
        raise typer.BadParameter("Pass exactly one of --course or --all.")
    config = load_config()
    ensure_home(config)
    conn = connect(config.db_path)
    links: list[LinkReport] = []
    try:
        courses = Courses(conn).all()
        if course is not None:
            courses = [c for c in courses if c.course.upper() == course.upper()]
            if not courses:
                raise typer.BadParameter(
                    f"No course {course!r}; add it with `brightlearn courses add`."
                )
        if courses:
            with wiring.open_knowledge(config, conn) as knowledge:
                step = LinkStep(knowledge, Manifest(conn), config.nlm_source_cap, include_code)
                links = [step.run(c.course) for c in courses]
    finally:
        conn.close()

    if not links:
        console.print("No courses yet; add one with `brightlearn courses add`.")
        return
    print_links(links)
    if any(r.failures for r in links):
        raise typer.Exit(1)


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
