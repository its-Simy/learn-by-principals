"""The Studio's practice exams: what ``brightlearn exam create|take|grade`` does, over HTTP.

The exam's JSON file is the record. ``take`` and its steps change it on the request's thread and
the grade job on the jobs thread, and each rewrites the whole file from the copy it loaded, so
they never overlap: the take POSTs refuse while a grade job is queued or running on the course,
the grade route queues only a handed-in attempt, and both sides check and act under
``engine.lock``. Reads (GET take, results, markdown) need no lock: every write replaces the
file whole.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from api.deps import SAFE_NAME, ConfigDep, CourseDep, DbDep, EngineDep, named_file
from api.engine import Engine, JobKind, JobRunning, Resources
from api.schemas.studio import AnswerIn, ExamCreateIn, ExamOut, ResultsOut, TakeOut, TextOut
from api.schemas.system import JobOut
from core.analysis.challenge import ChallengeStore
from core.config import Config
from core.context.compiler import ContextCompiler
from core.exams.coverage import plan
from core.exams.generate import GenerationError, QuestionGenerator
from core.exams.grade import ExamGrader, GradeError
from core.exams.paper import (
    ExamFileError,
    exams_dir,
    latest_attempt,
    load,
    new_exam,
    new_paths,
    save,
    to_markdown,
)
from core.exams.spec import ExamSpec, SpecError, parse_spec, spec_template
from core.exams.take import ExamTaker
from core.memory.learner import LearnerMemory
from core.sessions import guard

log = logging.getLogger(__name__)

router = APIRouter(tags=["exams"])

GRADING: frozenset[JobKind] = frozenset({"exam_grade"})

GRADING_409 = "a grade job is queued or running on the course (`job_running`)"
TAKE_CONFLICT: dict[int | str, dict[str, Any]] = {409: {"description": GRADING_409.capitalize()}}
STEP_CONFLICT: dict[int | str, dict[str, Any]] = {
    409: {"description": f"No unfinished attempt (`no_open_attempt`), or {GRADING_409}"}
}


@router.get("/courses/{course}/exams")
def list_exams(course: CourseDep, cfg: ConfigDep) -> list[ExamOut]:
    """Newest first. A file that isn't an exam is skipped, not a 422 for the whole list."""
    exams = []
    for path in exams_dir(cfg.vault_root, course).glob("*.json"):
        if not SAFE_NAME.fullmatch(path.stem):
            continue  # a file copied in by hand under a name the URLs can't carry
        try:
            exams.append(ExamOut.from_core(path.stem, load(path)))
        except ExamFileError as exc:
            log.warning("Skipping %s: %s", path, exc)
    return sorted(exams, key=lambda e: e.created_at, reverse=True)


@router.get("/courses/{course}/exams/template")
def exam_template(course: CourseDep) -> TextOut:
    """A spec to start from, for the new-exam editor. Declared before ``/exams/{exam_id}``,
    which would otherwise take "template" for an exam id (no exam file is named that)."""
    return TextOut(text=spec_template(course))


@router.get("/courses/{course}/exams/{exam_id}")
def get_exam(course: CourseDep, exam_id: str, cfg: ConfigDep) -> ExamOut:
    return ExamOut.from_core(exam_id, load(exam_path(cfg, course, exam_id)))


@router.post("/courses/{course}/exams")
def create_exam(course: CourseDep, body: ExamCreateIn, conn: DbDep, engine: EngineDep) -> JobOut:
    """The spec is checked now (422), so a typo never waits behind a podcast. Its grounding
    queries start fresh NotebookLM conversations (P66), so a course with an open tutor session
    is refused, under the lock a session start takes."""
    try:
        doc = yaml.safe_load(body.spec_yaml)
    except yaml.YAMLError as exc:
        raise SpecError(f"Not valid YAML: {exc}") from exc
    spec = parse_spec(doc)
    if spec.course != course:
        raise SpecError(f"The spec is for {spec.course}; this is {course}")
    with engine.lock:
        guard(LearnerMemory(conn), course)
        job = engine.jobs.submit("exam_create", course, partial(create_job, spec))
    return JobOut.from_core(job)


def create_job(spec: ExamSpec, r: Resources) -> dict[str, Any]:
    """The body of ``brightlearn exam create``: plan, generate and critique, then write the
    exam's .json and .md."""
    guard(r.learner, spec.course)  # again on this thread: a CLI session may have opened since
    learner, manifest = r.learner, r.manifest
    concepts = learner.concepts(spec.course)
    mastery = {c.concept_id: m for c in concepts if (m := learner.get_mastery(c.concept_id))}
    coverage = plan(spec, concepts, mastery)
    router = r.router()  # the Critic is kept off the Questioner's providers by the generator
    generator = QuestionGenerator(
        router, router, ContextCompiler(r.knowledge, learner, manifest), manifest
    )
    report = generator.generate(coverage)
    if not report.questions:
        raise GenerationError("No valid questions were generated; nothing written")
    json_path, md_path = new_paths(r.config.vault_root, spec.course, spec.slug, datetime.now())
    exam = new_exam(json_path.stem, coverage, report)
    save(json_path, exam)
    md_path.write_text(to_markdown(exam))
    return {
        "exam_id": json_path.stem,
        "questions": len(report.questions),
        "planned": coverage.total,
        "generator_providers": list(report.generator_providers),
        "critic_provider": report.critic_provider,
        "regenerated": list(report.regenerated),
        "dropped": list(report.dropped),
        "critiqued": report.critiqued,
        "critique_skipped": report.critique_skipped,
        "no_week": list(coverage.no_week),
        "unmatched_include": list(coverage.unmatched_include),
        "unmatched_exclude": list(coverage.unmatched_exclude),
    }


@router.get("/courses/{course}/exams/{exam_id}/markdown")
def exam_markdown(course: CourseDep, exam_id: str, cfg: ConfigDep) -> TextOut:
    """The printable paper, answer key and rubrics included (after a rule)."""
    return TextOut(text=to_markdown(load(exam_path(cfg, course, exam_id))))


@router.get("/courses/{course}/exams/{exam_id}/take")
def attempt_state(course: CourseDep, exam_id: str, cfg: ConfigDep) -> TakeOut:
    """The latest attempt as it stands, read only: unlike POST, it never opens an attempt, so
    the take view can reload freely. The file is replaced whole on every write, so a read
    never sees half of one."""
    exam = load(exam_path(cfg, course, exam_id))
    attempt = latest_attempt(exam)
    in_progress = attempt is not None and not attempt.get("finished_at")
    return TakeOut.from_core(exam, attempt, resumed=in_progress)


@router.post("/courses/{course}/exams/{exam_id}/take", responses=TAKE_CONFLICT)
def take_exam(course: CourseDep, exam_id: str, cfg: ConfigDep, engine: EngineDep) -> TakeOut:
    """Resume the unfinished attempt, or start the next one after a finished attempt."""
    path = exam_path(cfg, course, exam_id)
    with engine.lock:
        refuse_while_grading(engine, course)
        taker = ExamTaker(path)
    return TakeOut.from_core(taker.exam, taker.attempt, taker.resumed)


@router.post(
    "/courses/{course}/exams/{exam_id}/take/answer",
    response_model=TakeOut,
    responses=STEP_CONFLICT,
)
def answer_question(
    course: CourseDep, exam_id: str, body: AnswerIn, cfg: ConfigDep, engine: EngineDep
) -> TakeOut | JSONResponse:
    """Answer the current question; a multiple-choice reply that picks no option is a 422."""
    path = exam_path(cfg, course, exam_id)
    return step(engine, course, path, lambda taker: taker.answer(body.reply))


@router.post(
    "/courses/{course}/exams/{exam_id}/take/skip",
    response_model=TakeOut,
    responses=STEP_CONFLICT,
)
def skip_question(
    course: CourseDep, exam_id: str, cfg: ConfigDep, engine: EngineDep
) -> TakeOut | JSONResponse:
    return step(engine, course, exam_path(cfg, course, exam_id), ExamTaker.skip)


@router.post(
    "/courses/{course}/exams/{exam_id}/take/finish",
    response_model=TakeOut,
    responses=STEP_CONFLICT,
)
def finish_attempt(
    course: CourseDep, exam_id: str, cfg: ConfigDep, engine: EngineDep
) -> TakeOut | JSONResponse:
    """Hand the attempt in; questions not answered yet are graded as skipped."""
    return step(engine, course, exam_path(cfg, course, exam_id), ExamTaker.finish)


@router.post("/courses/{course}/exams/{exam_id}/grade")
def grade_exam(course: CourseDep, exam_id: str, cfg: ConfigDep, engine: EngineDep) -> JobOut:
    """Only a handed-in attempt is queued (422 otherwise): a job the grader would refuse would
    still hold up every take step on the course until its turn came, perhaps behind a podcast.
    Checked under the lock the take steps hold, so the attempt can't change in between."""
    path = exam_path(cfg, course, exam_id)
    with engine.lock:
        attempt = latest_attempt(load(path))
        if attempt is None:
            raise GradeError(f"{exam_id} hasn't been taken yet")
        if not attempt.get("finished_at"):
            raise GradeError(f"Attempt {attempt['attempt']} isn't finished; finish it first")
        job = engine.jobs.submit("exam_grade", course, partial(grade_job, path))
    return JobOut.from_core(job)


def grade_job(path: Path, r: Resources) -> dict[str, Any]:
    """The body of ``brightlearn exam grade``."""
    report = ExamGrader(r.learner, r.router(), ChallengeStore(r.conn)).grade(path)
    return {
        "exam_id": report.exam_id,
        "attempt": report.attempt,
        "correct": report.correct,
        "graded": report.graded,
        "unanswered": report.unanswered,
        "already_graded": report.already_graded,
        "ungraded": list(report.ungraded),
        "grader": report.grader,
        "grader_error": report.grader_error,
        "new_evidence": list(report.new_evidence),
        "queued_challenges": report.queued_challenges,
        "scores": [
            {
                "concept_id": s.concept_id,
                "name": s.name,
                "correct": s.correct,
                "total": s.total,
                "level_before": s.level_before,
                "level_after": s.level_after,
            }
            for s in report.scores
        ],
    }


@router.get("/courses/{course}/exams/{exam_id}/results")
def exam_results(course: CourseDep, exam_id: str, cfg: ConfigDep) -> ResultsOut:
    """The latest graded attempt, question by question with the reference answers, and per
    concept as the file recorded it; 404 until an attempt is graded."""
    results = ResultsOut.from_core(exam_id, load(exam_path(cfg, course, exam_id)))
    if results is None:
        raise HTTPException(404, f"No graded attempt of {exam_id} yet")
    return results


def exam_path(cfg: Config, course: str, exam_id: str) -> Path:
    return named_file(exams_dir(cfg.vault_root, course), exam_id, ".json", what="exam")


def refuse_while_grading(engine: Engine, course: str) -> None:
    job = engine.jobs.running(course, GRADING)
    if job is not None:
        raise JobRunning(job)


def step(
    engine: Engine, course: str, path: Path, act: Callable[[ExamTaker], None]
) -> TakeOut | JSONResponse:
    """Answer, skip or finish, only on an unfinished attempt: ``ExamTaker`` on a finished one
    would quietly open the next attempt and record the step there."""
    with engine.lock:
        refuse_while_grading(engine, course)
        attempt = latest_attempt(load(path))
        if attempt is None or attempt.get("finished_at"):
            return no_open_attempt(path.stem, attempt)
        taker = ExamTaker(path)
        act(taker)
    return TakeOut.from_core(taker.exam, taker.attempt, taker.resumed)


def no_open_attempt(exam_id: str, attempt: dict[str, Any] | None) -> JSONResponse:
    """A 409 with a ``code``, as every 409 this API sends carries one."""
    if attempt is None:
        detail = f"{exam_id} hasn't been started; take it first"
    else:
        detail = (
            f"Attempt {attempt['attempt']} of {exam_id} is finished; "
            "take the exam again to start the next attempt"
        )
    return JSONResponse({"code": "no_open_attempt", "detail": detail}, status_code=409)
