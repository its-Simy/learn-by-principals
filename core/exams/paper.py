"""The exam file: ``vault/courses/{course}/exams/{exam}-{timestamp}.json`` plus a readable ``.md``.

The JSON is the record: the spec, the plan, the questions, every attempt with timestamped
answers, and every grade with the evidence id it wrote. It is rewritten atomically after each
change, so an interrupted ``take`` or ``grade`` loses at most the answer in progress.
"""

from __future__ import annotations

import json
import os
import string
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from core.exams.coverage import CoveragePlan
from core.exams.generate import GenerationReport
from core.ledger.ledger import utcnow

LETTERS = string.ascii_uppercase


class ExamFileError(Exception):
    pass


def exams_dir(vault_root: Path, course: str) -> Path:
    return vault_root / "courses" / course / "exams"


def new_paths(vault_root: Path, course: str, exam_slug: str, now: datetime) -> tuple[Path, Path]:
    """``{exam}-{YYYYmmdd-HHMMSS}.json`` and ``.md``, with ``-N`` added if taken."""
    folder = exams_dir(vault_root, course)
    stem = f"{exam_slug}-{now.strftime('%Y%m%d-%H%M%S')}"
    path, n = folder / f"{stem}.json", 1
    while path.exists():
        n += 1
        path = folder / f"{stem}-{n}.json"
    return path, path.with_suffix(".md")


def new_exam(exam_id: str, plan: CoveragePlan, report: GenerationReport) -> dict[str, Any]:
    spec = plan.spec
    return {
        "id": exam_id,
        "course": spec.course,
        "exam": spec.exam,
        "created_at": utcnow(),
        "spec": asdict(spec),
        "plan": [
            {
                "concept_id": r.concept.concept_id,
                "concept": r.concept.name,
                "n_questions": r.n_questions,
                "difficulty_mix": r.difficulty_mix,
                "format_mix": r.format_mix,
                "level": r.level,
                "target_level": r.target_level,
                "tags": list(r.tags),
            }
            for r in plan.rows
        ],
        "questions": [{"index": i, **q.to_json()} for i, q in enumerate(report.questions)],
        "generation": {
            "planned": plan.total,
            "generator_providers": report.generator_providers,
            "critic_provider": report.critic_provider,
            "critique": report.critique,
            "regenerated": report.regenerated,
            "dropped": report.dropped,
            "critique_skipped": report.critique_skipped,
        },
        "attempts": [],
    }


def load(path: Path) -> dict[str, Any]:
    try:
        exam = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ExamFileError(f"{path}: {exc}") from exc
    if not isinstance(exam, dict) or not isinstance(exam.get("questions"), list):
        raise ExamFileError(f"{path} is not a BrightLearn exam file")
    exam.setdefault("attempts", [])
    return exam


def save(path: Path, exam: dict[str, Any]) -> None:
    """Write to a hidden temp file beside ``path``, then rename it into place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    try:
        part.write_text(json.dumps(exam, indent=2, ensure_ascii=False) + "\n")
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)


def concept_names(exam: dict[str, Any]) -> dict[str, str]:
    return {row["concept_id"]: row["concept"] for row in exam.get("plan", [])}


def to_markdown(exam: dict[str, Any]) -> str:
    """The questions, then the answer key and rubrics after a rule (so the top can be printed)."""
    names = concept_names(exam)
    lines = [
        f"# {exam['exam']} · {exam['course']}",
        "",
        f"Practice exam `{exam['id']}`, {exam['spec']['mode']} mode, "
        f"{len(exam['questions'])} questions. Take it with "
        f"`brightlearn exam take <this exam's .json>`.",
        "",
    ]
    for q in exam["questions"]:
        n = q["index"] + 1
        label = q["format"].replace("_", " ")
        lines += [
            f"## {n}. {names.get(q['concept_id'], q['concept_id'])} · {label} · {q['difficulty']}",
            "",
            q["stem"],
            "",
        ]
        for letter, option in zip(LETTERS, q.get("options") or [], strict=False):
            lines.append(f"- **{letter}.** {option}")
        if q.get("options"):
            lines.append("")
    lines += ["---", "", "## Answer key", ""]
    for q in exam["questions"]:
        answer = q["answer"]
        if q.get("options"):
            answer = f"{LETTERS[q['options'].index(answer)]}. {answer}"
        lines += [f"{q['index'] + 1}. **{answer}**", f"   Rubric: {q['rubric']}"]
    return "\n".join(lines) + "\n"


def mc_choice(question: dict[str, Any], reply: str) -> str | None:
    """The option a multiple-choice reply picks: a letter ("b", "B.", "(b)") or the option text."""
    options = question.get("options") or []
    text = reply.strip()
    letter = text.strip("().: ").upper()
    if len(letter) == 1 and letter in LETTERS[: len(options)]:
        return options[LETTERS.index(letter)]
    for option in options:
        if option.strip().lower() == text.lower():
            return option
    return None


def latest_attempt(exam: dict[str, Any]) -> dict[str, Any] | None:
    return exam["attempts"][-1] if exam["attempts"] else None
