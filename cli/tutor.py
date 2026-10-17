from __future__ import annotations

import typer
from rich.console import Console
from rich.markdown import Markdown

from cli.sessions import refuse_if_session_open
from core import wiring
from core.config import load_config
from core.memory.db import connect
from core.personas import PersonaError
from core.tutor import HELP

console = Console()


def tutor(
    course: str = typer.Option(..., help="Course code, e.g. CSE220."),
    persona: str = typer.Option("simplifier", help="Teaching persona to start with."),
) -> None:
    """Interactive tutoring grounded in the course's NotebookLM sources."""
    course = course.upper()
    config = load_config()
    conn = connect(config.db_path)
    try:
        # A second session's first query would delete this course's live conversation (P66).
        refuse_if_session_open(conn, course)
        try:
            providers = wiring.model_providers(config, ("teaching", "analysis"))
        except (KeyError, ValueError) as exc:
            raise typer.BadParameter(f"[routing] in {config.config_path}: {exc}") from exc
        with wiring.open_knowledge(config, conn) as knowledge:
            try:
                session = wiring.tutor(config, conn, knowledge, providers, course, persona)
            except PersonaError as exc:
                raise typer.BadParameter(str(exc)) from exc
            row = session.start()
            console.print(f"Session {row.session_id} · {course} · {session.persona}. {HELP}")
            opening = session.opening()
            if opening:
                console.print(Markdown(opening))
            while not session.ended:
                try:
                    line = console.input("[bold]you>[/] ")
                except (EOFError, KeyboardInterrupt):
                    line = "/end"
                reply = session.handle(line)
                if reply:
                    console.print(Markdown(reply))
            console.print(f"[dim]Transcript: {session.transcript_path}[/]")
    finally:
        conn.close()
