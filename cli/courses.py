"""``brightlearn courses``: imports, ``sync``, ``generate`` and ``podcast`` need a course row."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from core.config import ensure_home, load_config
from core.memory.db import CourseError, Courses, Manifest, connect

app = typer.Typer(no_args_is_help=True, help="The courses files are uploaded to.")
console = Console()


@app.command("list")
def list_cmd() -> None:
    """Every course, with its term folder and number of stored files."""
    config = load_config()
    ensure_home(config)
    conn = connect(config.db_path)
    try:
        manifest = Manifest(conn)
        table = Table("Code", "Name", "Term", "Files", "Folder")
        for c in Courses(conn).all():
            files = sum(1 for r in manifest.all(c.course) if r.local_path)
            folder = escape(str(c.root(config.storage_root)))
            table.add_row(c.course, escape(c.name), c.term, str(files), folder)
    finally:
        conn.close()
    console.print(table)


@app.command("add")
def add_cmd(
    code: str = typer.Argument(..., help="Course code, e.g. CSE220; it names the course folder."),
    name: str = typer.Option(..., help='Course name, e.g. "Systems Fundamentals".'),
    term: str | None = typer.Option(None, help="Term folder, e.g. Fall-2026. Default: from date."),
) -> None:
    """Add a course so files can be uploaded to it."""
    config = load_config(term=term)
    ensure_home(config)
    conn = connect(config.db_path)
    try:
        row = Courses(conn).add(code.upper(), name, config.term)
    except CourseError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        conn.close()
    console.print(
        f"Added {row.course} ({escape(row.name)}); files go under "
        f"{escape(str(row.root(config.storage_root)))}"
    )
