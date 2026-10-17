"""``brightlearn sessions list|close``, and how a command refuses while a session is open (P66).

``core.sessions.guard`` holds the rule; this module words the refusal for the terminal, saying
so when the session has been idle over two hours (BL-040).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import typer
from rich.console import Console
from rich.table import Column, Table

from core.config import load_config
from core.maintenance import STALE_AFTER
from core.memory.db import connect
from core.memory.learner import LearnerError, LearnerMemory, idle_for
from core.sessions import SessionOpen, guard

app = typer.Typer(no_args_is_help=True, help="Tutor sessions.")
console = Console()

ASK_HINT = "Ask inside that session with [bold]/ask <question>[/]"


def refuse_if_session_open(conn: sqlite3.Connection, course: str, hint: str | None = None) -> None:
    """Exit 1 when ``course`` has an open tutor session; ``hint`` says what to do instead."""
    now = datetime.now(UTC)
    try:
        guard(LearnerMemory(conn), course, now)
    except SessionOpen as exc:
        session = exc.session
        lines = [
            f"[red]Tutor session {session.session_id} is open on {course}[/] (started "
            f"{session.started_at}); NotebookLM keeps one live conversation per course.",
        ]
        if exc.stale:
            hours = idle_for(session, now).total_seconds() / 3600
            lines.append(
                f"[yellow]It looks stale: no turn for {hours:.0f} hours.[/] If it's finished or "
                "crashed, close it."
            )
        if hint:
            lines.append(f"{hint}, or end it first:")
        else:
            lines.append("End it first:")
        lines.append(f"  brightlearn sessions close --id {session.session_id}")
        console.print("\n".join(lines))
        raise typer.Exit(1) from exc


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
        Column("Session", no_wrap=True),
        "Course",
        "Started",
        Column("Ended", no_wrap=True),
        "Tutor",
        "Analyzer",
    )
    now = datetime.now(UTC)
    for r in rows:
        if r.ended_at:
            ended = r.ended_at[:16]
        elif idle_for(r, now) > STALE_AFTER:
            ended = "[yellow]open, stale[/]"
        else:
            ended = "[yellow]open[/]"
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
