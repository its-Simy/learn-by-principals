from __future__ import annotations

import typer
from rich.console import Console
from rich.markdown import Markdown

from cli import common
from core.config import load_config
from core.context.compiler import ContextCompiler
from core.ledger.ledger import Ledger
from core.memory.db import Manifest, connect
from core.memory.learner import LearnerMemory
from core.memory.vault import Vault
from core.personas import PersonaError
from core.router.router import Router
from core.tutor import HELP, Tutor

console = Console()


def tutor(
    course: str = typer.Option(..., help="Course code, e.g. CSE220."),
    persona: str = typer.Option("simplifier", help="Teaching persona to start with."),
) -> None:
    """Interactive tutoring grounded in the course's NotebookLM sources."""
    course = course.upper()
    config = load_config()
    conn = connect(config.db_path)
    learner = LearnerMemory(conn)
    try:
        providers = common.model_providers(config, ("teaching", "analysis"))
    except (KeyError, ValueError) as exc:
        raise typer.BadParameter(f"[routing] in {config.config_path}: {exc}") from exc
    # v0: the order comes from config.toml [routing] teaching (default claude, then codex).
    router = Router(providers, Ledger(conn), list(config.routing["teaching"]))
    try:
        with common.open_knowledge(config, conn) as knowledge:
            compiler = ContextCompiler(knowledge, learner, Manifest(conn))
            try:
                session = Tutor(
                    course,
                    persona,
                    compiler,
                    router,
                    learner,
                    Vault(config.vault_root),
                    on_end=common.session_end_hook(config, conn, providers),
                )
            except PersonaError as exc:
                raise typer.BadParameter(str(exc)) from exc
            row = session.start()
            console.print(f"Session {row.session_id} · {course} · {session.persona}. {HELP}")
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
