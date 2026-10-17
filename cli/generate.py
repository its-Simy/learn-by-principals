from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime
from enum import StrEnum
from pathlib import Path

import typer
from rich.console import Console

from cli import common
from core.config import Config, load_config
from core.memory.db import Courses, connect

console = Console()


class Kind(StrEnum):
    quiz = "quiz"
    audio = "audio"
    flashcards = "flashcards"
    report = "report"


def generated_dir(config: Config, conn: sqlite3.Connection, course: str) -> Path:
    """Beside the course's files, under the course row's term rather than today's."""
    row = Courses(conn).get(course)
    if row is None:
        raise typer.BadParameter(f"No course {course!r}; add it with `brightlearn courses add`.")
    return row.root(config.storage_root) / "_generated"


def generate(
    kind: Kind = typer.Argument(..., help="What to generate."),
    course: str = typer.Option(..., help="Course code, e.g. CSE220."),
    prompt_file: Path | None = typer.Option(
        None, exists=True, dir_okay=False, help="Markdown instructions for NotebookLM."
    ),
    format: str | None = typer.Option(
        None, help="audio: brief|deep-dive|critique|debate. report: briefing_doc|study_guide|…"
    ),
    length: str | None = typer.Option(None, help="audio: short|default|long."),
    out: Path | None = typer.Option(None, help="Write here instead of the course _generated/."),
) -> None:
    """Generate a NotebookLM artifact from a course's sources."""
    course = course.upper()
    instructions = prompt_file.read_text() if prompt_file else None
    config = load_config()
    conn = connect(config.db_path)
    try:
        folder = generated_dir(config, conn, course)
        with common.open_knowledge(config, conn) as knowledge:
            notebook_id = knowledge.ensure_notebook(course)
            if kind is Kind.quiz:
                spec = {"instructions": instructions} if instructions else {}
                quiz = knowledge.generate_quiz(notebook_id, spec)
                dest = _destination(folder, kind, ".json", out)
                dest.write_text(json.dumps(quiz, indent=2))
            elif kind is Kind.audio:
                path = knowledge.generate_audio(notebook_id, instructions or "", format, length)
                dest = _move(path, _destination(folder, kind, path.suffix, out))
            else:
                options: dict[str, str] = {}
                if instructions:
                    options["prompt" if kind is Kind.report else "instructions"] = instructions
                if format:
                    options["format"] = format
                path = knowledge.generate(notebook_id, kind.value, options)
                dest = _move(path, _destination(folder, kind, path.suffix, out))
    finally:
        conn.close()
    console.print(f"[green]{kind.value}[/] -> {dest}")


def _destination(folder: Path, kind: Kind, ext: str, out: Path | None) -> Path:
    if out is not None:
        dest = out
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = folder / f"{stamp}-{kind.value}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def _move(src: Path, dest: Path) -> Path:
    shutil.move(src, dest)
    return dest
