"""``brightlearn concepts seed|apply``: draft a course's concepts, review by hand, then load."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.syntax import Syntax

from cli.sessions import refuse_if_session_open
from core import wiring
from core.config import load_config
from core.memory.db import Manifest, connect
from core.memory.learner import LearnerMemory
from core.memory.seeding import (
    DraftNotReviewed,
    SeedingError,
    apply,
    draft_diff,
    drafts_dir,
    latest_draft,
    list_drafts,
    seed,
)

app = typer.Typer(no_args_is_help=True, help="Course concept graph.")
console = Console()


@app.command("seed")
def seed_cmd(course: str = typer.Option(..., help="Course code, e.g. CSE220.")) -> None:
    """Ask NotebookLM for the course's concepts and write a new draft YAML for review."""
    course = course.upper()
    config = load_config()
    conn = connect(config.db_path)
    previous = latest_draft(config.vault_root, course)
    try:
        # The seed query starts a fresh conversation, which would end a live tutor's (P66).
        refuse_if_session_open(conn, course)
        with wiring.open_knowledge(config, conn) as knowledge:
            path, concepts = seed(knowledge, Manifest(conn), course, config.vault_root)
    except SeedingError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        conn.close()
    diff = draft_diff(previous, path)
    if previous is None:
        console.print(Syntax(path.read_text(), "yaml"))
    elif diff:
        console.print(Syntax(diff, "diff"))
    else:
        console.print(f"[dim]Same as {previous.name}.[/]")
    console.print(
        f"\n{len(concepts)} concepts drafted in {path}"
        + (f" (earlier drafts are kept; diff against {previous.name} above)" if previous else "")
        + ".\nReview and edit it, set [bold]reviewed: true[/], then run "
        f"[bold]brightlearn concepts apply --course {course}[/]."
    )


@app.command("apply")
def apply_cmd(
    course: str = typer.Option(..., help="Course code, e.g. CSE220."),
    draft: Path | None = typer.Option(
        None,
        help="The draft to load (a path, or a file name in the course folder). "
        "Default: the newest draft.",
    ),
) -> None:
    """Load a reviewed draft into the concepts table. Safe to re-run."""
    course = course.upper()
    config = load_config()
    if draft is None:
        path = latest_draft(config.vault_root, course)
        if path is None:
            console.print(f"[red]No draft for {course}; run `brightlearn concepts seed` first.[/]")
            raise typer.Exit(1)
    elif draft.exists():
        path = draft
    else:
        path = drafts_dir(config.vault_root, course) / draft.name
    conn = connect(config.db_path)
    try:
        result = apply(path, LearnerMemory(conn))
    except SeedingError as exc:
        console.print(f"[red]{exc}[/]")
        if isinstance(exc, DraftNotReviewed):
            console.print(f"Edit {path} and set `reviewed: true`.")
        if isinstance(exc, DraftNotReviewed) and draft is None:
            older = [p.name for p in list_drafts(config.vault_root, course) if p != path]
            if older:
                console.print("Earlier drafts: " + ", ".join(older) + " (pick one with --draft).")
        raise typer.Exit(1) from exc
    finally:
        conn.close()
    console.print(
        f"Applied {path.name}: {len(result.added)} added, {len(result.updated)} updated, "
        f"{len(result.retired)} retired ({len(result.unchanged)} unchanged)."
    )
    if result.retired:
        console.print(
            "[yellow]Retired (kept with their mastery and evidence): "
            + ", ".join(c.name for c in result.retired)
            + ". Add an `aliases:` entry if one was renamed.[/]"
        )
    if result.unknown_prerequisites:
        console.print(
            "[yellow]Prerequisites not defined as concepts: "
            + ", ".join(result.unknown_prerequisites)
            + "[/]"
        )
