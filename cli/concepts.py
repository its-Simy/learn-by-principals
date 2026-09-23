"""``brightlearn concepts seed|apply``: draft a course's concepts, review by hand, then load."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.syntax import Syntax

from cli import common
from core.config import load_config
from core.memory.db import Manifest, connect
from core.memory.learner import LearnerMemory
from core.memory.seeding import SeedingError, apply, draft_path, seed

app = typer.Typer(no_args_is_help=True, help="Course concept graph.")
console = Console()


@app.command("seed")
def seed_cmd(course: str = typer.Option(..., help="Course code, e.g. CSE220.")) -> None:
    """Ask NotebookLM for the course's concepts and write a draft YAML for review."""
    course = course.upper()
    config = load_config()
    conn = connect(config.db_path)
    try:
        with common.open_knowledge(config, conn) as knowledge:
            path, concepts = seed(knowledge, Manifest(conn), course, config.vault_dir)
    except SeedingError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        conn.close()
    console.print(Syntax(path.read_text(), "yaml"))
    console.print(
        f"\n{len(concepts)} concepts drafted in {path}.\n"
        "Review and edit it, set [bold]reviewed: true[/], then run "
        f"[bold]brightlearn concepts apply --course {course}[/]."
    )


@app.command("apply")
def apply_cmd(course: str = typer.Option(..., help="Course code, e.g. CSE220.")) -> None:
    """Load the reviewed draft into the concepts table. Safe to re-run."""
    config = load_config()
    path = draft_path(config.vault_dir, course.upper())
    conn = connect(config.db_path)
    try:
        result = apply(path, LearnerMemory(conn))
    except SeedingError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    finally:
        conn.close()
    console.print(f"Applied {len(result.applied)} concepts from {path}.")
    if result.unknown_prerequisites:
        console.print(
            "[yellow]Prerequisites not defined as concepts: "
            + ", ".join(result.unknown_prerequisites)
            + "[/]"
        )
