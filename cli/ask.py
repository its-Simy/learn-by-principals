from __future__ import annotations

import typer
from rich.console import Console

from cli import common
from core.config import load_config
from core.memory.db import Manifest, connect
from core.sync.classify import BUCKETS

console = Console()


def parse_buckets(value: str | None) -> list[str] | None:
    if not value:
        return None
    buckets = [b.strip() for b in value.split(",") if b.strip()]
    unknown = sorted(set(buckets) - set(BUCKETS))
    if unknown:
        raise typer.BadParameter(f"Unknown bucket(s) {unknown}; choose from {', '.join(BUCKETS)}")
    return buckets


def ask(
    question: str = typer.Argument(..., help="The question, in quotes."),
    course: str = typer.Option(..., help="Course code, e.g. CSE220."),
    sources: str | None = typer.Option(
        None, help="Only these buckets, comma-separated, e.g. syllabus,lectures."
    ),
) -> None:
    """Ask a grounded question about a course's sources."""
    buckets = parse_buckets(sources)
    config = load_config()
    conn = connect(config.db_path)
    try:
        rows = [r for r in Manifest(conn).all(course.upper()) if r.notebook_source_id]
        titles = {r.notebook_source_id: r for r in rows}
        source_ids = None
        if buckets is not None:
            source_ids = [r.notebook_source_id for r in rows if r.bucket in buckets]
            if not source_ids:
                raise typer.BadParameter(f"No {course} sources in NotebookLM for {sources}.")
        with common.open_knowledge(config, conn) as knowledge:
            notebook_id = knowledge.ensure_notebook(course.upper())
            answer = knowledge.query(notebook_id, question, source_ids)
    finally:
        conn.close()

    console.print(answer.text)
    if answer.citations:
        console.print("\n[bold]Sources[/]")
    for n, citation in enumerate(answer.citations, start=1):
        row = titles.get(citation.source_id)
        label = f"{row.filename} ({row.bucket})" if row else f"source {citation.source_id}"
        excerpt = " ".join(citation.excerpt.split())
        console.print(f"[{n}] {label}" + (f"\n    [dim]{excerpt[:200]}[/]" if excerpt else ""))
