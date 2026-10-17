"""``brightlearn podcast``: an Audio Overview shaped by the learner model (BL-034)."""

from __future__ import annotations

import shutil
from datetime import datetime

import typer
from rich.console import Console
from rich.markup import escape

from cli.generate import generated_dir
from core import wiring
from core.config import load_config
from core.exams.spec import SpecError, find_spec
from core.memory.db import connect
from core.memory.learner import LearnerMemory
from core.memory.vault import Vault
from core.podcast.compiler import build_podcast_context
from core.podcast.episodes import PodcastStore

console = Console()


def podcast(
    course: str = typer.Option(..., help="Course code, e.g. CSE220."),
    exam: str | None = typer.Option(
        None, help="Frame it for an exam: a spec YAML, or the name of an exam already created."
    ),
    format: str = typer.Option("deep-dive", help="brief|deep-dive|critique|debate."),
    length: str | None = typer.Option(None, help="short|default|long."),
) -> None:
    """Compile the learner's state into instructions and generate an Audio Overview."""
    course = course.upper()
    config = load_config()
    try:
        spec = find_spec(config.vault_root, course, exam) if exam else None
    except SpecError as exc:
        raise typer.BadParameter(str(exc)) from exc
    conn = connect(config.db_path)
    try:
        folder = generated_dir(config, conn, course)
        context = build_podcast_context(course, spec, LearnerMemory(conn), Vault(config.vault_root))
        with wiring.open_knowledge(config, conn) as knowledge:
            notebook_id = knowledge.ensure_notebook(course)
            audio = knowledge.generate_audio(notebook_id, context.text, format, length)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        folder.mkdir(parents=True, exist_ok=True)
        instructions = folder / f"{stamp}-podcast.md"
        instructions.write_text(context.text)
        dest = folder / f"{stamp}-podcast{audio.suffix}"
        shutil.move(audio, dest)
        PodcastStore(conn).record(course, context.concept_ids, instructions, dest)
    finally:
        conn.close()
    focus = ", ".join(c.name for c, _ in context.focus) or "(none)"
    console.print(f"Focus: {escape(focus)}")
    if context.skip:
        console.print(
            f"[dim]Skipped as mastered: {escape(', '.join(c.name for c in context.skip))}[/]"
        )
    console.print(f"[green]podcast[/] -> {dest}\n[dim]instructions -> {instructions}[/]")
