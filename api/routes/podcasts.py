"""The Studio's Audio Overview card: what ``brightlearn podcast`` does, and the episodes it made."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from api.deps import ConfigDep, CourseDep, DbDep, EngineDep
from api.engine import Resources
from api.schemas.studio import EpisodeOut, PodcastIn, TextOut
from api.schemas.system import JobOut
from core.exams.spec import ExamSpec, saved_spec
from core.memory.db import Courses
from core.podcast.compiler import build_podcast_context
from core.podcast.episodes import Episode, PodcastStore

router = APIRouter(tags=["podcasts"])


@router.post("/courses/{course}/podcast")
def generate_podcast(
    course: CourseDep,
    cfg: ConfigDep,
    conn: DbDep,
    engine: EngineDep,
    body: PodcastIn | None = None,
) -> JobOut:
    """``exam`` names an exam already created, looked up in the vault only: unlike the CLI's
    ``--exam``, never a spec file's path, since a web page has no business naming files here.
    An unknown one is a 422 now, not a failed job twenty minutes from now. No session guard:
    generating audio starts no conversation, as with the CLI."""
    body = body or PodcastIn()
    spec = saved_spec(cfg.vault_root, course, body.exam) if body.exam else None
    course_row = Courses(conn).get(course)
    assert course_row is not None  # CourseDep checked
    folder = course_row.root(cfg.storage_root) / "_generated"
    job = engine.jobs.submit(
        "podcast", course, partial(podcast_job, course, spec, body.format, body.length, folder)
    )
    return JobOut.from_core(job)


def podcast_job(
    course: str,
    spec: ExamSpec | None,
    format: str,
    length: str | None,
    folder: Path,
    r: Resources,
) -> dict[str, Any]:
    """The body of ``brightlearn podcast``: the brief and the audio side by side in the course's
    ``_generated``, and a ``podcasts`` row naming the concepts it targeted."""
    context = build_podcast_context(course, spec, r.learner, r.vault)
    notebook_id = r.knowledge.ensure_notebook(course)
    audio = r.knowledge.generate_audio(notebook_id, context.text, format, length)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    instructions = folder / f"{stamp}-podcast.md"
    instructions.write_text(context.text)
    dest = folder / f"{stamp}-podcast{audio.suffix}"
    shutil.move(audio, dest)
    episode = PodcastStore(r.conn).record(course, context.concept_ids, instructions, dest)
    return {
        "episode": EpisodeOut.from_core(episode).model_dump(mode="json"),
        "focus": [c.name for c, _ in context.focus],
        "skipped": [c.name for c in context.skip],  # mastered and well retained
    }


@router.get("/courses/{course}/podcasts")
def list_podcasts(course: CourseDep, conn: DbDep) -> list[EpisodeOut]:
    """Newest first."""
    return [EpisodeOut.from_core(e) for e in reversed(PodcastStore(conn).all(course))]


@router.get(
    "/podcasts/{podcast_id}/audio",
    response_class=FileResponse,
    responses={200: {"content": {"audio/mp4": {}}, "description": "The episode's audio"}},
)
def podcast_audio(podcast_id: int, conn: DbDep) -> FileResponse:
    """NotebookLM's Audio Overviews are .m4a, so ``<audio>`` gets ``audio/mp4``."""
    path = episode_file(episode(conn, podcast_id).audio_path, podcast_id)
    return FileResponse(path, media_type="audio/mp4")


@router.get("/podcasts/{podcast_id}/brief")
def podcast_brief(podcast_id: int, conn: DbDep) -> TextOut:
    """The instructions the episode was generated from."""
    path = episode_file(episode(conn, podcast_id).instruction_path, podcast_id)
    return TextOut(text=path.read_text())


def episode(conn: sqlite3.Connection, podcast_id: int) -> Episode:
    found = PodcastStore(conn).get(podcast_id)
    if found is None:
        raise HTTPException(404, f"No podcast {podcast_id}")
    return found


def episode_file(recorded: str, podcast_id: int) -> Path:
    path = Path(recorded)
    if not path.is_file():
        raise HTTPException(404, f"Podcast {podcast_id}'s file {path.name} is gone")
    return path
