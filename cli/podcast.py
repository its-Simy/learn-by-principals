"""``brightlearn podcast``: an Audio Overview shaped by the learner model (BL-034)."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape

from cli import common
from cli.generate import generated_dir
from core.config import Config, load_config
from core.exams.paper import exams_dir
from core.exams.spec import ExamSpec, SpecError, load_spec, parse_spec
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
    spec = _find_spec(config, course, exam) if exam else None
    conn = connect(config.db_path)
    try:
        folder = generated_dir(config, conn, course)
        context = build_podcast_context(course, spec, LearnerMemory(conn), Vault(config.vault_root))
        with common.open_knowledge(config, conn) as knowledge:
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


def _find_spec(config: Config, course: str, name: str) -> ExamSpec:
    """A spec file path, or the spec saved in the newest created exam with that name."""
    path = Path(name).expanduser()
    if path.is_file():
        try:
            return load_spec(path)
        except SpecError as exc:
            raise typer.BadParameter(str(exc)) from exc
    wanted = _key(name)
    for exam_file in sorted(exams_dir(config.vault_root, course).glob("*.json"), reverse=True):
        try:
            saved = json.loads(exam_file.read_text()).get("spec") or {}
        except (OSError, json.JSONDecodeError):
            continue
        if _key(str(saved.get("exam", ""))) == wanted:
            fields = {k: v for k, v in saved.items() if v not in (None, [], ())}
            return parse_spec(fields)
    raise typer.BadParameter(
        f"No spec file {name!r} and no created {course} exam named {name!r}; "
        "pass a spec YAML path or run `brightlearn exam create` first."
    )


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())
