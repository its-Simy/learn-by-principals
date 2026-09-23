"""Question generation and critique (BL-032): Questioner drafts, a Critic on another provider
reviews the whole draft once, and only the flagged questions are regenerated.

Every question is validated strictly against ``SCHEMA_KEYS`` and the slot it fills (concept,
format, difficulty). An invalid or missing question gets one more try on its own; a second
failure drops it and logs why (``GenerationReport.dropped``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from core.context.compiler import ContextCompiler
from core.exams.coverage import CoveragePlan, PlanRow
from core.exams.spec import DIFFICULTIES, FORMATS, ExamSpec
from core.jsonutil import extract_json_array
from core.memory.db import Manifest
from core.personas import load, render
from core.providers.models.base import ModelError, ModelResult, TaskPackage
from core.router.router import Router

log = logging.getLogger(__name__)

MAX_TRIES = 2  # per question: the first draft, then one retry on its own
SCHEMA_KEYS = ("stem", "options", "answer", "rubric", "difficulty", "concept_id", "format")
REQUIRED_KEYS = ("stem", "answer", "rubric", "difficulty", "concept_id", "format")
MC_OPTIONS = (3, 6)  # a multiple-choice question has this many options, inclusive
SOURCE_BUCKETS = {"study-guides": "exams"}  # spec source name -> bucket, where they differ

SCHEMA_TEXT = """A JSON array only, one object per question, with exactly these keys:
{{"stem": "<the question>",
  "options": ["<option>", ...],        (multiple_choice only: 4 distinct options; omit otherwise)
  "answer": "<for multiple_choice, the exact text of the correct option>",
  "rubric": "<what a full-credit answer must contain>",
  "difficulty": "easy" | "medium" | "hard",
  "concept_id": "{concept_id}",
  "format": "multiple_choice" | "short_answer" | "coding"}}
No other keys, no prose outside the array."""

CRITIC_SCHEMA = """Reply with a JSON array only: [{"index": <question index>, "issue": "<what is
wrong>", "fix": "<the concrete change>"}]. Flag only real problems: not grounded in the sources,
ambiguous (more than one defensible answer), wrong answer key, difficulty tag that doesn't fit,
or a question that doesn't test its concept. Output [] if every question is sound."""


class GenerationError(Exception):
    pass


@dataclass(frozen=True)
class Slot:
    concept_id: str
    format: str
    difficulty: str


@dataclass
class Question:
    stem: str
    answer: str
    rubric: str
    difficulty: str
    concept_id: str
    format: str
    options: list[str] | None = None
    provider: str | None = None  # who wrote it (not part of the model's schema)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        if data["options"] is None:
            del data["options"]
        return data


@dataclass
class GenerationReport:
    questions: list[Question] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    critique: list[dict[str, Any]] = field(default_factory=list)
    regenerated: list[int] = field(default_factory=list)  # indices rewritten after critique
    generator_providers: list[str] = field(default_factory=list)
    critic_provider: str | None = None
    critique_skipped: str | None = None


# -- validation -------------------------------------------------------------------------------


def validate(item: Any, slot: Slot | None = None) -> Question:
    """A Question from one model item, or ValueError naming the first problem."""
    if not isinstance(item, dict):
        raise ValueError(f"not an object: {str(item)[:80]}")
    extra = sorted(set(item) - set(SCHEMA_KEYS))
    if extra:
        raise ValueError(f"unexpected key(s) {extra}")
    missing = [k for k in REQUIRED_KEYS if k not in item]
    if missing:
        raise ValueError(f"missing key(s) {missing}")
    for key in REQUIRED_KEYS:
        if not isinstance(item[key], str) or not item[key].strip():
            raise ValueError(f"{key} must be a non-empty string")
    fmt, difficulty = item["format"], item["difficulty"]
    if fmt not in FORMATS:
        raise ValueError(f"format {fmt!r} is not one of {FORMATS}")
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"difficulty {difficulty!r} is not one of {DIFFICULTIES}")
    options = item.get("options")
    if fmt == "multiple_choice":
        low, high = MC_OPTIONS
        if not isinstance(options, list) or not low <= len(options) <= high:
            raise ValueError(f"multiple_choice needs {low}-{high} options")
        if any(not isinstance(o, str) or not o.strip() for o in options):
            raise ValueError("options must be non-empty strings")
        if len({o.strip() for o in options}) != len(options):
            raise ValueError("options repeat")
        if item["answer"].strip() not in {o.strip() for o in options}:
            raise ValueError("answer is not one of the options")
    elif options is not None:
        raise ValueError(f"{fmt} questions have no options")
    if slot is not None:
        wanted = (slot.concept_id, slot.format, slot.difficulty)
        got = (item["concept_id"], fmt, difficulty)
        if got != wanted:
            raise ValueError(f"asked for {wanted}, got {got}")
    return Question(
        stem=item["stem"].strip(),
        answer=item["answer"].strip(),
        rubric=item["rubric"].strip(),
        difficulty=difficulty,
        concept_id=item["concept_id"],
        format=fmt,
        options=[o.strip() for o in options] if fmt == "multiple_choice" else None,
    )


def slots(row: PlanRow) -> list[Slot]:
    """One slot per question in the row, pairing its formats with its difficulties."""
    formats = [f for f, n in row.format_mix.items() for _ in range(n)]
    difficulties = [d for d, n in row.difficulty_mix.items() for _ in range(n)]
    return [Slot(row.concept.concept_id, f, d) for f, d in zip(formats, difficulties, strict=True)]


# -- generation -------------------------------------------------------------------------------


class QuestionGenerator:
    """``generator`` runs the Questioner (task ``question_gen``); ``critic_router`` runs the
    Critic and is always kept off every provider that wrote a question (principle 6)."""

    def __init__(
        self,
        generator: Router,
        critic_router: Router,
        compiler: ContextCompiler,
        manifest: Manifest | None = None,
    ) -> None:
        self._generator = generator
        self._critic = critic_router
        self._compiler = compiler
        self._manifest = manifest

    def generate(self, plan: CoveragePlan) -> GenerationReport:
        """One grounded NotebookLM query per concept, reused for its retries and rewrites."""
        report = GenerationReport()
        source_ids = self.source_ids(plan.spec)
        sources = {
            row.concept.concept_id: self._compiler.sources(
                _grounding_question(row), plan.spec.course, source_ids
            )
            for row in plan.rows
        }
        for row in plan.rows:
            report.questions += self._row(plan.spec, row, sources[row.concept.concept_id], report)
        if report.questions:
            self._critique(plan, report, sources)
        return report

    def source_ids(self, spec: ExamSpec) -> list[str] | None:
        """NotebookLM source ids in the spec's ``sources`` buckets (None: every source)."""
        if not spec.sources or self._manifest is None:
            return None
        buckets = {SOURCE_BUCKETS.get(s, s) for s in spec.sources}
        ids = [
            r.notebook_source_id
            for r in self._manifest.all(spec.course)
            if r.notebook_source_id and r.bucket in buckets
        ]
        if not ids:
            log.warning("No linked %s sources in %s; using every source", spec.course, buckets)
        return ids or None

    # -- per row ----------------------------------------------------------------------------

    def _row(
        self, spec: ExamSpec, row: PlanRow, source: str, report: GenerationReport
    ) -> list[Question]:
        wanted = slots(row)
        result = self._run(self._generator, self._task(spec, row, wanted, source), report)
        filled: list[Question | None] = [None] * len(wanted)
        problems: list[str] = [""] * len(wanted)
        items = extract_json_array(result.text)
        if items is None:
            problems = ["the answer was not a JSON array"] * len(wanted)
            items = []
        for item in items:
            open_slots = [i for i, q in enumerate(filled) if q is None]
            if not open_slots:
                break
            try:
                question = validate(item)
            except ValueError as exc:
                problems[open_slots[0]] = str(exc)
                continue
            match = next((i for i in open_slots if _fits(question, wanted[i])), None)
            if match is None:
                problems[open_slots[0]] = (
                    f"no open slot for {question.format}/{question.difficulty}"
                )
                continue
            question.provider = result.provider
            filled[match] = question
        out = []
        for i, slot in enumerate(wanted):
            question = filled[i]
            if question is None:
                question = self._retry(spec, row, slot, source, problems[i] or "missing", report)
            if question is not None:
                out.append(question)
        return out

    def _retry(
        self,
        spec: ExamSpec,
        row: PlanRow,
        slot: Slot,
        source: str,
        problem: str,
        report: GenerationReport,
    ) -> Question | None:
        """The second and last try for one question; None (dropped and logged) if it fails."""
        note = f"An earlier attempt at this question was rejected: {problem}. Follow the schema."
        task = self._task(spec, row, [slot], source, note)
        result = self._run(self._generator, task, report)
        items = extract_json_array(result.text) or []
        try:
            question = validate(items[0] if items else None, slot)
        except ValueError as exc:
            reason = f"{slot.concept_id} {slot.format}/{slot.difficulty}: {problem}; then {exc}"
            log.warning("Dropped a question after %d tries: %s", MAX_TRIES, reason)
            report.dropped.append(reason)
            return None
        question.provider = result.provider
        return question

    def _task(
        self,
        spec: ExamSpec,
        row: PlanRow,
        wanted: list[Slot],
        source: str,
        note: str = "",
    ) -> TaskPackage:
        concept = row.concept
        level = f"target level {row.target_level}"
        if "transfer" in row.tags:
            level += " (transfer: an unfamiliar variant, not a textbook repeat)"
        listed = "\n".join(
            f"{n}. {s.format}, {s.difficulty}" for n, s in enumerate(wanted, start=1)
        )
        user = (
            f"## Exam\n{spec.exam} ({spec.course}), {spec.mode} mode\n\n"
            f"## Concept\n{concept.name} (concept_id {concept.concept_id}); learner at level "
            f"{row.level}/5; {level}\n\n"
            f"## Write exactly {len(wanted)} question(s)\n{listed}\n\n"
            f"## Course sources (grounded in NotebookLM)\n{source}\n\n"
            f"## Output\n{SCHEMA_TEXT.format(concept_id=concept.concept_id)}"
            + (f"\n\n## Note\n{note}" if note else "")
        )
        system = render(load("questioner"), {"course": spec.course})
        return TaskPackage(
            "question_gen",
            "questioner",
            system,
            user,
            400 * len(wanted),
            {"course": spec.course, "concepts": [concept.concept_id]},
        )

    # -- critique ---------------------------------------------------------------------------

    def _critique(
        self, plan: CoveragePlan, report: GenerationReport, sources: dict[str, str]
    ) -> None:
        """One Critic pass over the whole draft; flagged questions are regenerated once."""
        authors = set(report.generator_providers)
        draft = [{"index": i, **q.to_json()} for i, q in enumerate(report.questions)]
        for item in draft:
            item.pop("provider", None)
        user = (
            f"## Exam draft: {plan.spec.exam} ({plan.spec.course})\n"
            f"{json.dumps(draft, indent=1)}\n\n## Output\n{CRITIC_SCHEMA}"
        )
        system = render(load("critic"), {"course": plan.spec.course})
        task = TaskPackage("critique", "critic", system, user, 1500, {"course": plan.spec.course})
        try:
            result = self._critic.run(task, exclude=authors)
        except ModelError as exc:
            report.critique_skipped = f"no critic: {exc}"
            log.warning("Exam draft not critiqued: %s", exc)
            return
        report.critic_provider = result.provider
        items = extract_json_array(result.text)
        if items is None:
            report.critique_skipped = "the critic's answer was not a JSON array"
            log.warning("Exam draft not critiqued: %s", result.text[:200])
            return
        flagged: dict[int, dict[str, Any]] = {}
        for item in items:
            index = item.get("index") if isinstance(item, dict) else None
            if isinstance(index, int) and 0 <= index < len(report.questions):
                flagged.setdefault(index, item)
            else:
                log.warning("Ignored critic item: %s", str(item)[:120])
        report.critique = list(flagged.values())
        rows = {r.concept.concept_id: r for r in plan.rows}
        for index, item in sorted(flagged.items()):
            old = report.questions[index]
            slot = Slot(old.concept_id, old.format, old.difficulty)
            row = rows[old.concept_id]
            note = (
                f"The Critic flagged this question: {json.dumps(old.to_json())}\n"
                f"Issue: {item.get('issue', '')}\nFix: {item.get('fix', '')}\n"
                "Write a corrected replacement."
            )
            new = self._rewrite(plan.spec, row, slot, sources[old.concept_id], note, report)
            if new is None:
                log.warning("Kept question %d as drafted: its rewrite was invalid", index)
                continue
            report.questions[index] = new
            report.regenerated.append(index)

    def _rewrite(
        self,
        spec: ExamSpec,
        row: PlanRow,
        slot: Slot,
        source: str,
        note: str,
        report: GenerationReport,
    ) -> Question | None:
        task = self._task(spec, row, [slot], source, note)
        exclude = {report.critic_provider} if report.critic_provider else set()
        result = self._run(self._generator, task, report, exclude)
        items = extract_json_array(result.text) or []
        try:
            question = validate(items[0] if items else None, slot)
        except ValueError:
            return None
        question.provider = result.provider
        return question

    # -- plumbing ---------------------------------------------------------------------------

    def _run(
        self,
        router: Router,
        task: TaskPackage,
        report: GenerationReport,
        exclude: set[str] | None = None,
    ) -> ModelResult:
        try:
            result = router.run(task, exclude=exclude or set())
        except ModelError as exc:
            raise GenerationError(f"Question generation could not run: {exc}") from exc
        if result.provider not in report.generator_providers:
            report.generator_providers.append(result.provider)
        return result


def _fits(question: Question, slot: Slot) -> bool:
    return (question.concept_id, question.format, question.difficulty) == (
        slot.concept_id,
        slot.format,
        slot.difficulty,
    )


def _grounding_question(row: PlanRow) -> str:
    return (
        f"How do the course materials present {row.concept.name}? Give the key definitions, a "
        "worked example, and the mistakes students commonly make."
    )
