"""``brightlearn sessions list|close``, and the one-live-conversation-per-course guard (P66).

A tutor session owns its course's live NotebookLM conversation until it ends. Anything else that
would start a fresh conversation on that course (which deletes the latest one) refuses while a
session is open.
"""

from __future__ import annotations

import sqlite3

import typer
from rich.console import Console
from rich.table import Column, Table

from core.config import load_config
from core.memory.db import connect
from core.memory.learner import LearnerError, LearnerMemory

app = typer.Typer(no_args_is_help=True, help="Tutor sessions.")
console = Console()

ASK_HINT = "Ask inside that session with [bold]/ask <question>[/]"


def refuse_if_session_open(conn: sqlite3.Connection, course: str, hint: str | None = None) -> None:
    """Exit 1 when ``course`` has an open tutor session; ``hint`` says what to do instead."""
    open_rows = LearnerMemory(conn).open_sessions(course)
    if not open_rows:
        return
    session = open_rows[0]
    lines = [
        f"[red]Tutor session {session.session_id} is open on {course}[/] (started "
        f"{session.started_at}); NotebookLM keeps one live conversation per course.",
    ]
    if hint:
        lines.append(f"{hint}, or end it first:")
    else:
        lines.append("End it first:")
    lines.append(f"  brightlearn sessions close --id {session.session_id}")
    console.print("\n".join(lines))
    raise typer.Exit(1)


@app.command("list")
def list_cmd(
    course: str | None = typer.Option(None, help="Only this course code."),
    open_only: bool = typer.Option(False, "--open", help="Only sessions that haven't ended."),
) -> None:
    """Tutor sessions, newest first."""
    config = load_config()
    conn = connect(config.db_path)
    try:
        rows = LearnerMemory(conn).sessions(course.upper() if course else None, open_only)
    finally:
        conn.close()
    if not rows:
        console.print("No sessions.")
        return
    table = Table(
        Column("Session", no_wrap=True), "Course", "Started", "Ended", "Tutor", "Analyzer"
    )
    for r in rows:
        ended = r.ended_at[:16] if r.ended_at else "[yellow]open[/]"
        table.add_row(
            r.session_id,
            r.course,
            r.started_at[:16],
            ended,
            r.tutor_provider or "",
            r.analyzer_provider or "",
        )
    console.print(table)


@app.command("close")
def close_cmd(
    session_id: str | None = typer.Option(None, "--id", help="The session to close."),
    all_open: bool = typer.Option(False, "--all", help="Every open session."),
) -> None:
    """Mark open sessions ended (e.g. after a crash). The Analyzer is not run."""
    if (session_id is None) == (not all_open):
        raise typer.BadParameter("Pass exactly one of --id or --all.")
    config = load_config()
    conn = connect(config.db_path)
    learner = LearnerMemory(conn)
    try:
        ids = [session_id] if session_id else [r.session_id for r in learner.open_sessions()]
        closed = []
        for sid in ids:
            try:
                closed.append(learner.close_session(sid))
            except LearnerError as exc:
                console.print(f"[red]{exc}[/]")
                raise typer.Exit(1) from exc
    finally:
        conn.close()
    for row in closed:
        console.print(f"Closed {row.session_id} ({row.course}).")
    if not closed:
        console.print("No open sessions.")
