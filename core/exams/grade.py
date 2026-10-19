"""Grading an exam attempt (BL-033). Every graded answer becomes one evidence row; mastery moves
only through the Analyzer's rule (``apply_proposal``), citing those rows.

- multiple choice: graded locally against the answer key
- short answer and coding: one ``critic`` call for all of them, against each rubric, on the
  ``analysis`` routing order, never on a provider that wrote the questions
- evidence: ``applied`` when correct, ``failed`` when wrong; strength by difficulty
- idempotent: a question already graded in this attempt (per the exam file, or per an evidence
  row this attempt already wrote) is never graded again
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.analysis.analyzer import STRENGTH_CONFIDENCE, AnalysisReport, apply_proposal
from core.analysis.challenge import ChallengeStore, queue_challenges
from core.exams.paper import concept_names, latest_attempt, load, save
from core.jsonutil import extract_json_array
from core.ledger.ledger import utcnow
from core.memory.learner import LearnerError, LearnerMemory
from core.memory.schema import EVIDENCE_STRENGTHS
from core.personas import load as load_persona
from core.personas import render
from core.providers.models.base import ModelError, TaskPackage
from core.router.router import Router

log = logging.getLogger(__name__)

STRENGTH_BY_DIFFICULTY = {"easy": "weak", "medium": "moderate", "hard": "strong"}
PASS_RATIO = 0.75  # at or above: the concept is shown at the exam's target level
FAIL_RATIO = 0.25  # at or below: one level down
LOCAL = "local"  # source_provider for answers graded without a model

GRADER_SCHEMA = """Reply with a JSON array only, one object per answer:
[{"index": <question index>, "correct": true | false, "feedback": "<one sentence: what was right
or what is missing>"}]. Judge each answer against its rubric only; "correct" means it meets the
rubric. Grade every answer listed."""


class GradeError(Exception):
    pass


@dataclass(frozen=True)
class ConceptScore:
    concept_id: str
    name: str
    correct: int
    total: int  # graded answers
    level_before: int | None
    level_after: int | None


@dataclass
class GradeReport:
    exam_id: str
    attempt: int
    scores: list[ConceptScore] = field(default_factory=list)
    new_evidence: list[str] = field(default_factory=list)
    already_graded: int = 0
    ungraded: list[int] = field(default_factory=list)  # open answers the grader didn't return
    unanswered: int = 0
    grader: str | None = None
    grader_error: str | None = None
    analysis: AnalysisReport | None = None
    queued_challenges: int = 0

    @property
    def correct(self) -> int:
        return sum(s.correct for s in self.scores)

    @property
    def graded(self) -> int:
        return sum(s.total for s in self.scores)


def exam_proposal(current: int, results: list[bool], target_level: int) -> int:
    """The level an exam's results for one concept propose."""
    ratio = sum(results) / len(results)
    if ratio >= PASS_RATIO:
        return max(current, target_level)
    if ratio <= FAIL_RATIO:
        return max(current - 1, 0)
    return current


class ExamGrader:
    def __init__(
        self,
        learner: LearnerMemory,
        router: Router,
        challenges: ChallengeStore | None = None,
        now: Callable[[], str] = utcnow,
    ) -> None:
        self._learner = learner
        self._router = router
        self._challenges = challenges
        self._now = now

    def grade(self, path: Path) -> GradeReport:
        exam = load(path)
        attempt = latest_attempt(exam)
        if attempt is None:
            raise GradeError(f"{path.name} hasn't been taken yet: brightlearn exam take {path}")
        if not attempt.get("finished_at"):
            raise GradeError(
                f"Attempt {attempt['attempt']} isn't finished; `brightlearn exam take` resumes it"
            )
        session_id = f"exam:{exam['id']}:{attempt['attempt']}"
        report = GradeReport(exam["id"], attempt["attempt"])
        report.analysis = AnalysisReport(session_id, LOCAL)
        grades: dict[str, Any] = attempt.setdefault("grades", {})
        answers: dict[str, Any] = attempt["answers"]
        answered = answered_questions(exam, answers)
        report.unanswered = len(exam["questions"]) - len(answered)
        todo = [q for q in answered if str(q["index"]) not in grades]
        report.already_graded = len(answered) - len(todo)

        def record(q: dict[str, Any], correct: bool, feedback: str, grader: str) -> None:
            evidence_id = self._evidence(q, answers[str(q["index"])], correct, grader, session_id)
            if evidence_id is None:
                report.ungraded.append(q["index"])
                return
            grades[str(q["index"])] = {
                "correct": correct,
                "feedback": feedback,
                "grader": grader,
                "evidence_id": evidence_id,
                "graded_at": self._now(),
            }
            report.new_evidence.append(evidence_id)
            save(path, exam)

        for q in todo:
            if q["format"] == "multiple_choice":
                right = answers[str(q["index"])]["answer"] == q["answer"]
                record(q, right, "" if right else f"The answer is: {q['answer']}", LOCAL)
        open_questions = [q for q in todo if q["format"] != "multiple_choice"]
        if open_questions:
            results = self._grade_open(exam, open_questions, answers, report)
            for q in open_questions:
                if q["index"] in results:
                    correct, feedback = results[q["index"]]
                    record(q, correct, feedback, report.grader or LOCAL)
                else:
                    report.ungraded.append(q["index"])

        self._mastery(exam, attempt, answered, grades, report, path)
        if self._challenges is not None and report.analysis.needs_challenge:
            report.queued_challenges = len(queue_challenges(self._challenges, report.analysis))
        report.scores = self._scores(exam, attempt, answered, grades)
        return report

    # -- steps ------------------------------------------------------------------------------

    def _evidence(
        self,
        q: dict[str, Any],
        answer: dict[str, Any],
        correct: bool,
        grader: str,
        session_id: str,
    ) -> str | None:
        """This question's evidence id for the attempt: an existing row if one was already
        written (e.g. the file wasn't saved after it), otherwise a new one."""
        ref = f"Q{q['index'] + 1}:"
        for e in self._learner.evidence(q["concept_id"]):
            if e.session_id == session_id and (e.excerpt_ref or "").startswith(ref):
                return e.evidence_id
        try:
            return self._learner.add_evidence(
                q["concept_id"],
                "applied" if correct else "failed",
                STRENGTH_BY_DIFFICULTY[q["difficulty"]],
                session_id=session_id,
                source_provider=grader,
                excerpt_ref=f"{ref} {answer['answer']}"[:500],
            )
        except LearnerError as exc:
            log.warning("No evidence for question %d: %s", q["index"], exc)
            return None

    def _grade_open(
        self,
        exam: dict[str, Any],
        questions: list[dict[str, Any]],
        answers: dict[str, Any],
        report: GradeReport,
    ) -> dict[int, tuple[bool, str]]:
        blocks = [
            f"### Question {q['index']} ({q['format'].replace('_', ' ')}, {q['difficulty']})\n"
            f"Question: {q['stem']}\nRubric: {q['rubric']}\nReference answer: {q['answer']}\n"
            f"Learner's answer:\n{answers[str(q['index'])]['answer']}"
            for q in questions
        ]
        user = (
            f"## Answers to grade: {exam['exam']} ({exam['course']})\n\n"
            + "\n\n".join(blocks)
            + f"\n\n## Output\n{GRADER_SCHEMA}"
        )
        system = render(load_persona("critic"), {"course": exam["course"]})
        task = TaskPackage(
            "grade", "critic", system, user, 200 * len(questions) + 200, {}, output_format="json"
        )
        # The grader never runs on a provider that wrote the questions (BL-040).
        writers = set(exam.get("generation", {}).get("generator_providers") or [])
        try:
            result = self._router.run(task, exclude=writers)
        except ModelError as exc:
            report.grader_error = str(exc)
            log.warning("Open answers not graded: %s", exc)
            return {}
        report.grader = result.provider
        wanted = {q["index"] for q in questions}
        results: dict[int, tuple[bool, str]] = {}
        for item in extract_json_array(result.text) or []:
            if not isinstance(item, dict):
                continue
            index, correct = item.get("index"), item.get("correct")
            if index in wanted and isinstance(correct, bool) and index not in results:
                results[index] = (correct, str(item.get("feedback") or ""))
        if not results:
            report.grader_error = f"no usable grades in: {result.text[:200]}"
        return results

    def _mastery(
        self,
        exam: dict[str, Any],
        attempt: dict[str, Any],
        answered: list[dict[str, Any]],
        grades: dict[str, Any],
        report: GradeReport,
        path: Path,
    ) -> None:
        """Once every answered question on a concept is graded, propose its level (once)."""
        assert report.analysis is not None
        done: dict[str, Any] = attempt.setdefault("mastery", {})
        for row in exam.get("plan", []):
            concept_id = row["concept_id"]
            questions = [q for q in answered if q["concept_id"] == concept_id]
            if concept_id in done or not questions:
                continue
            if any(str(q["index"]) not in grades for q in questions):
                continue  # wait until the grader has returned all of them
            graded = [grades[str(q["index"])] for q in questions]
            results = [g["correct"] for g in graded]
            mastery = self._learner.get_mastery(concept_id)
            current = mastery.level if mastery else 0
            proposed = exam_proposal(current, results, row["target_level"])
            going_up = proposed > current
            strengths = [
                STRENGTH_BY_DIFFICULTY[q["difficulty"]]
                for q, g in zip(questions, graded, strict=True)
                if g["correct"] == going_up
            ] or ["weak"]
            strongest = max(strengths, key=EVIDENCE_STRENGTHS.index)
            apply_proposal(
                self._learner,
                report.analysis,
                concept_id,
                current,
                proposed,
                STRENGTH_CONFIDENCE[strongest],
                [g["evidence_id"] for g in graded],
            )
            after = self._learner.get_mastery(concept_id)
            done[concept_id] = {
                "before": current,
                "proposed": proposed,
                "after": after.level if after else current,
                "at": self._now(),
            }
            save(path, exam)

    @staticmethod
    def _scores(
        exam: dict[str, Any],
        attempt: dict[str, Any],
        answered: list[dict[str, Any]],
        grades: dict[str, Any],
    ) -> list[ConceptScore]:
        names = concept_names(exam)
        done = attempt.get("mastery", {})
        scores = []
        for concept_id in dict.fromkeys(q["concept_id"] for q in exam["questions"]):
            graded = [
                grades[str(q["index"])]
                for q in answered
                if q["concept_id"] == concept_id and str(q["index"]) in grades
            ]
            change = done.get(concept_id, {})
            scores.append(
                ConceptScore(
                    concept_id,
                    names.get(concept_id, concept_id),
                    sum(g["correct"] for g in graded),
                    len(graded),
                    change.get("before"),
                    change.get("after"),
                )
            )
        return scores


def answered_questions(exam: dict[str, Any], answers: dict[str, Any]) -> list[dict[str, Any]]:
    """The questions with an answer that wasn't a skip; a question never reached counts as
    skipped, as when an attempt is finished early."""
    return [
        q for q in exam["questions"] if not answers.get(str(q["index"]), {}).get("skipped", True)
    ]


def attempt_scores(exam: dict[str, Any], attempt: dict[str, Any]) -> list[ConceptScore]:
    """Per concept, from what the file recorded for ``attempt`` (its grades and mastery
    changes), so a graded attempt's results can be shown again without grading it again."""
    answered = answered_questions(exam, attempt.get("answers") or {})
    return ExamGrader._scores(exam, attempt, answered, attempt.get("grades") or {})
