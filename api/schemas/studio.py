"""The Studio pane: concepts and their drafts, practice exams, Audio Overviews."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from core.exams.grade import ConceptScore, attempt_scores
from core.exams.paper import latest_graded_attempt
from core.exams.take import current_question
from core.memory.learner import Concept, Evidence, Mastery
from core.memory.seeding import ApplyResult
from core.podcast.episodes import Episode

log = logging.getLogger(__name__)

Format = Literal["multiple_choice", "short_answer", "coding"]


class ConceptOut(BaseModel):
    """A concept and its mastery; one with no evidence yet reads as level 0."""

    concept_id: str
    course: str
    name: str
    module: str | None
    prerequisites: list[str]
    exam_tags: list[str]
    week: int | None
    status: Literal["active", "retired"]  # retired: dropped by a reviewed draft, never deleted
    level: int
    confidence: float
    evidence_count: int
    retention_confidence: float | None
    last_evidence_at: str | None

    @classmethod
    def from_core(cls, concept: Concept, mastery: Mastery | None) -> ConceptOut:
        m = mastery or Mastery(concept.concept_id)
        return cls(
            concept_id=concept.concept_id,
            course=concept.course,
            name=concept.name,
            module=concept.module,
            prerequisites=list(concept.prerequisites),
            exam_tags=list(concept.exam_tags),
            week=concept.week,
            status=concept.status,
            level=m.level,
            confidence=m.confidence,
            evidence_count=m.evidence_count,
            retention_confidence=m.retention_confidence,
            last_evidence_at=m.last_evidence_at,
        )


class EvidenceOut(BaseModel):
    evidence_id: str
    concept_id: str
    session_id: str | None
    type: str
    strength: str
    source_provider: str | None
    excerpt_ref: str | None
    recorded_at: str

    @classmethod
    def from_core(cls, evidence: Evidence) -> EvidenceOut:
        return cls(
            evidence_id=evidence.evidence_id,
            concept_id=evidence.concept_id,
            session_id=evidence.session_id,
            type=evidence.type,
            strength=evidence.strength,
            source_provider=evidence.source_provider,
            excerpt_ref=evidence.excerpt_ref,
            recorded_at=evidence.recorded_at,
        )


class DraftOut(BaseModel):
    """A concept draft in the course's vault folder; ``latest`` is what apply loads by default."""

    name: str
    reviewed: bool
    latest: bool

    @classmethod
    def from_core(cls, path: Path, reviewed: bool, latest: bool) -> DraftOut:
        return cls(name=path.name, reviewed=reviewed, latest=latest)


class ApplyIn(BaseModel):
    draft: str | None = None  # a draft's name; the newest when left out


class ApplyOut(BaseModel):
    draft: str
    added: int
    updated: int
    unchanged: int
    retired: int  # kept with their mastery and evidence; an `aliases:` entry maps a rename
    retired_names: list[str]
    unknown_prerequisites: list[str]

    @classmethod
    def from_core(cls, draft: str, result: ApplyResult) -> ApplyOut:
        return cls(
            draft=draft,
            added=len(result.added),
            updated=len(result.updated),
            unchanged=len(result.unchanged),
            retired=len(result.retired),
            retired_names=[c.name for c in result.retired],
            unknown_prerequisites=list(result.unknown_prerequisites),
        )


class AttemptOut(BaseModel):
    attempt: int
    started_at: str
    finished_at: str | None
    answered: int  # skipped questions are counted in ``skipped``, not here
    skipped: int
    graded: int
    correct: int

    @classmethod
    def from_core(cls, attempt: dict[str, Any]) -> AttemptOut:
        answers = attempt.get("answers") or {}
        grades = attempt.get("grades") or {}
        skipped = sum(1 for a in answers.values() if a.get("skipped"))
        return cls(
            attempt=attempt["attempt"],
            started_at=attempt["started_at"],
            finished_at=attempt.get("finished_at"),
            answered=len(answers) - skipped,
            skipped=skipped,
            graded=len(grades),
            correct=sum(1 for g in grades.values() if g.get("correct")),
        )


class ExamOut(BaseModel):
    """An exam file's summary; no question text, so no answer can leak through it."""

    id: str  # the file's name without .json, as the URLs use it
    exam: str
    course: str
    created_at: str
    mode: str
    questions: int
    review: str | None  # "critiqued" or "uncritiqued" (BL-040)
    attempts: list[AttemptOut]

    @classmethod
    def from_core(cls, exam_id: str, exam: dict[str, Any]) -> ExamOut:
        attempts = []
        for n, attempt in enumerate(exam.get("attempts", []), start=1):
            if (
                isinstance(attempt, dict)
                and isinstance(attempt.get("attempt"), int)
                and isinstance(attempt.get("started_at"), str)
            ):
                attempts.append(AttemptOut.from_core(attempt))
            else:  # a hand edit: one bad attempt shouldn't hide the exam, or the whole list
                log.warning("%s: attempt %d has no number or start time; not shown", exam_id, n)
        return cls(
            id=exam_id,
            exam=exam.get("exam", exam_id),
            course=exam.get("course", ""),
            created_at=exam.get("created_at", ""),
            mode=(exam.get("spec") or {}).get("mode", "realistic"),
            questions=len(exam["questions"]),
            review=exam.get("review"),
            attempts=attempts,
        )


class ExamCreateIn(BaseModel):
    spec_yaml: str  # an ExamSpec, as the CLI's --spec file holds it


# Everything a learner may see of a question while taking the exam. QuestionOut is built from
# these keys only, never from the whole question, so answer, rubric and provider stay in the file.
QUESTION_KEYS = ("index", "stem", "options", "format", "difficulty", "concept_id")


class QuestionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    stem: str
    options: list[str] | None  # multiple choice only; answered by letter (A, B, ...) or text
    format: Format
    difficulty: Literal["easy", "medium", "hard"]
    concept_id: str

    @classmethod
    def from_core(cls, question: dict[str, Any]) -> QuestionOut:
        return cls(**{key: question.get(key) for key in QUESTION_KEYS})


class TakeOut(BaseModel):
    """Where the latest attempt stands. ``question`` is the next one to answer: null once the
    attempt is handed in (``finished``), or when every question has an answer and it can be.
    ``attempt`` is null only before the exam was ever taken."""

    attempt: int | None
    resumed: bool
    total: int
    answered: int
    skipped: int
    finished: bool
    question: QuestionOut | None

    @classmethod
    def from_core(
        cls, exam: dict[str, Any], attempt: dict[str, Any] | None, resumed: bool
    ) -> TakeOut:
        total = len(exam["questions"])
        if attempt is None:
            return cls(
                attempt=None,
                resumed=False,
                total=total,
                answered=0,
                skipped=0,
                finished=False,
                question=None,
            )
        summary = AttemptOut.from_core(attempt)
        finished = summary.finished_at is not None
        current = None if finished else current_question(exam, attempt)
        return cls(
            attempt=summary.attempt,
            resumed=resumed,
            total=total,
            answered=summary.answered,
            skipped=summary.skipped,
            finished=finished,
            question=QuestionOut.from_core(current) if current is not None else None,
        )


class AnswerIn(BaseModel):
    reply: str


# What a graded attempt's results show of each question: the learner's own answer and the
# reference answer are added beside these; the rubric and the question's author never are.
RESULT_KEYS = ("index", "stem", "options", "format", "concept_id")


class QuestionResultOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    stem: str
    options: list[str] | None
    format: Format
    concept_id: str
    your_answer: str | None  # null when skipped or never reached
    skipped: bool
    correct: bool | None  # null when not graded: skipped, or the grader didn't return it
    feedback: str | None
    reference_answer: str

    @classmethod
    def from_core(
        cls, question: dict[str, Any], answer: dict[str, Any] | None, grade: dict[str, Any] | None
    ) -> QuestionResultOut:
        return cls(
            **{key: question.get(key) for key in RESULT_KEYS},
            your_answer=answer.get("answer") if answer else None,
            skipped=answer is None or bool(answer.get("skipped")),
            correct=grade.get("correct") if grade else None,
            feedback=(grade.get("feedback") or None) if grade else None,
            reference_answer=str(question["answer"]),
        )


class ConceptScoreOut(BaseModel):
    concept_id: str
    name: str
    correct: int
    total: int  # graded answers on the concept
    level_before: int | None  # null until every answer on the concept is graded
    level_after: int | None

    @classmethod
    def from_core(cls, score: ConceptScore) -> ConceptScoreOut:
        return cls(
            concept_id=score.concept_id,
            name=score.name,
            correct=score.correct,
            total=score.total,
            level_before=score.level_before,
            level_after=score.level_after,
        )


class ResultsOut(BaseModel):
    """The latest graded attempt, read back from the exam file."""

    exam_id: str
    attempt: int
    finished_at: str
    correct: int
    graded: int
    questions: list[QuestionResultOut]
    scores: list[ConceptScoreOut]

    @classmethod
    def from_core(cls, exam_id: str, exam: dict[str, Any]) -> ResultsOut | None:
        """None when no attempt is graded. It picks the attempt itself, so no caller can hand
        it one still being taken, whose answers the reference answers would give away."""
        attempt = latest_graded_attempt(exam)
        if attempt is None:
            return None
        answers = attempt.get("answers") or {}
        grades = attempt["grades"]
        return cls(
            exam_id=exam_id,
            attempt=attempt["attempt"],
            finished_at=attempt["finished_at"],
            correct=sum(1 for g in grades.values() if g.get("correct")),
            graded=len(grades),
            questions=[
                QuestionResultOut.from_core(
                    q, answers.get(str(q["index"])), grades.get(str(q["index"]))
                )
                for q in exam["questions"]
            ],
            scores=[ConceptScoreOut.from_core(s) for s in attempt_scores(exam, attempt)],
        )


class PodcastIn(BaseModel):
    exam: str | None = None  # frame it for an exam already created, by its name
    format: Literal["brief", "deep-dive", "critique", "debate"] = "deep-dive"
    length: Literal["short", "default", "long"] | None = None


class EpisodeOut(BaseModel):
    id: int
    course: str
    concepts: list[str]  # the concept ids the episode targeted
    created_at: str
    audio_url: str
    brief_url: str  # the instructions NotebookLM was given

    @classmethod
    def from_core(cls, episode: Episode) -> EpisodeOut:
        return cls(
            id=episode.id,
            course=episode.course,
            concepts=list(episode.concepts),
            created_at=episode.created_at,
            audio_url=f"/api/podcasts/{episode.id}/audio",
            brief_url=f"/api/podcasts/{episode.id}/brief",
        )
