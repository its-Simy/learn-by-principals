"""``ExamSpec``: the editable YAML that describes one practice exam (master spec, "ExamSpec").

```yaml
course: CSE220
exam: Midterm 1
weeks: [1, 2, 3, 4, 5]
sources: [syllabus, study-guides, lectures]
formats: {multiple_choice: 10, short_answer: 5, coding: 3}
difficulty: {easy: 20, medium: 50, hard: 30}
mode: realistic          # realistic | weakness | challenge | diagnostic
include: [data representation, pointers]
exclude: [file I/O]
```

``formats`` are question counts. ``difficulty`` is percentages summing to 100, or counts summing
to the number of questions.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import yaml

from core.memory.vault import slug
from core.sync.classify import BUCKETS

FORMATS = ("multiple_choice", "short_answer", "coding")
DIFFICULTIES = ("easy", "medium", "hard")
MODES = ("realistic", "weakness", "challenge", "diagnostic")
# Buckets, plus "study-guides" (study guides are filed in the exams bucket).
SOURCES = (*BUCKETS, "study-guides")
MAX_QUESTIONS = 100

REQUIRED = ("course", "exam", "formats", "difficulty")
KEYS = (*REQUIRED, "weeks", "sources", "mode", "include", "exclude")


class SpecError(Exception):
    """The spec is invalid; the message lists every problem found."""


@dataclass(frozen=True)
class ExamSpec:
    course: str
    exam: str
    formats: dict[str, int]
    difficulty: dict[str, int]  # counts, summing to total_questions
    mode: str = "realistic"
    weeks: tuple[int, ...] = ()  # empty: every week
    sources: tuple[str, ...] = ()  # empty: every source
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()

    @property
    def total_questions(self) -> int:
        return sum(self.formats.values())

    @property
    def slug(self) -> str:
        return slug(self.exam)


def load_spec(path: Path) -> ExamSpec:
    try:
        doc = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise SpecError(f"{path}: not valid YAML: {exc}") from exc
    except OSError as exc:
        raise SpecError(f"{path}: {exc}") from exc
    try:
        return parse_spec(doc)
    except SpecError as exc:
        raise SpecError(f"{path}: {exc}") from exc


def find_spec(vault_root: Path, course: str, name: str) -> ExamSpec:
    """A spec file path, or the spec saved in the newest created exam with that name, so a
    podcast can be framed for an exam without keeping its YAML around."""
    path = Path(name).expanduser()
    if path.is_file():
        return load_spec(path)
    spec = _saved(vault_root, course, name)
    if spec is None:
        raise SpecError(
            f"No spec file {name!r} and no created {course} exam named {name!r}; "
            "pass a spec YAML path or run `brightlearn exam create` first."
        )
    return spec


def saved_spec(vault_root: Path, course: str, name: str) -> ExamSpec:
    """The spec saved in the newest created exam with that name, and never a file the caller
    names: what the API offers, since a web page has no business naming files here."""
    spec = _saved(vault_root, course, name)
    if spec is None:
        raise SpecError(f"No created {course} exam named {name!r}; create the exam first.")
    return spec


def _saved(vault_root: Path, course: str, name: str) -> ExamSpec | None:
    # paper imports coverage, which imports this module: importing paper at the top is a cycle.
    from core.exams.paper import exams_dir

    wanted = _key(name)
    for exam_file in sorted(exams_dir(vault_root, course).glob("*.json"), reverse=True):
        try:
            saved = json.loads(exam_file.read_text()).get("spec") or {}
        except (OSError, json.JSONDecodeError):
            continue
        if _key(str(saved.get("exam", ""))) == wanted:
            fields = {k: v for k, v in saved.items() if v not in (None, [], ())}
            return parse_spec(fields)
    return None


def spec_template(course: str) -> str:
    """A starting spec for ``course`` that ``parse_spec`` accepts, each key explained, so the
    web editor keeps no copy of the format of its own."""
    return f"""course: {course}
exam: Midterm 1
weeks: [1, 2, 3, 4, 5]  # leave out for every week
sources: [syllabus, study-guides, lectures]  # leave out for every source
formats: {{multiple_choice: 10, short_answer: 5, coding: 3}}  # question counts
difficulty: {{easy: 20, medium: 50, hard: 30}}  # percentages, or counts
mode: realistic  # {" | ".join(MODES)}
# include: [concept names]  # always covered
# exclude: [concept names]  # never covered
"""


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def parse_spec(doc: Any) -> ExamSpec:
    if not isinstance(doc, dict):
        raise SpecError("the spec must be a YAML mapping")
    problems: list[str] = []
    unknown = sorted(set(doc) - set(KEYS))
    if unknown:
        problems.append(f"unknown key(s) {unknown}; allowed: {', '.join(KEYS)}")
    missing = [k for k in REQUIRED if k not in doc]
    if missing:
        problems.append(f"missing key(s) {missing}")

    course = doc.get("course")
    if "course" in doc and not (isinstance(course, str) and course.strip()):
        problems.append("course must be a course code, e.g. CSE220")
    exam = doc.get("exam")
    if "exam" in doc and not (isinstance(exam, str) and exam.strip()):
        problems.append("exam must be a name, e.g. Midterm 1")

    formats = _counts(doc.get("formats"), FORMATS, "formats", problems)
    total = sum(formats.values())
    if isinstance(doc.get("formats"), dict) and total == 0:
        problems.append("formats ask for no questions")
    if total > MAX_QUESTIONS:
        problems.append(f"formats ask for {total} questions; the most is {MAX_QUESTIONS}")
    difficulty = _difficulty(doc.get("difficulty"), total, problems) if "difficulty" in doc else {}

    mode = doc.get("mode", "realistic")
    if mode not in MODES:
        problems.append(f"mode {mode!r} is not one of {', '.join(MODES)}")
    weeks = _list(doc.get("weeks"), "weeks", problems)
    if any(not isinstance(w, int) or isinstance(w, bool) or w < 1 for w in weeks):
        problems.append(f"weeks must be whole numbers from 1: {weeks}")
    sources = _list(doc.get("sources"), "sources", problems)
    bad_sources = [s for s in sources if s not in SOURCES]
    if bad_sources:
        problems.append(f"unknown source(s) {bad_sources}; choose from {', '.join(SOURCES)}")
    include = _names(doc.get("include"), "include", problems)
    exclude = _names(doc.get("exclude"), "exclude", problems)
    both = sorted({slug(n) for n in include} & {slug(n) for n in exclude})
    if both:
        problems.append(f"in both include and exclude: {both}")

    if problems:
        raise SpecError("; ".join(problems))
    return ExamSpec(
        course=course.strip().upper(),
        exam=exam.strip(),
        formats=formats,
        difficulty=difficulty,
        mode=mode,
        weeks=tuple(dict.fromkeys(weeks)),
        sources=tuple(dict.fromkeys(sources)),
        include=tuple(include),
        exclude=tuple(exclude),
    )


def _counts(value: Any, allowed: tuple[str, ...], key: str, problems: list[str]) -> dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        problems.append(f"{key} must be a mapping like {{{allowed[0]}: 10}}")
        return {}
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        problems.append(f"unknown {key} {unknown}; choose from {', '.join(allowed)}")
    counts: dict[str, int] = {}
    for name in allowed:
        n = value.get(name, 0)
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            problems.append(f"{key}.{name} must be a whole number >= 0, not {n!r}")
            continue
        if n:
            counts[name] = n
    return counts


def _difficulty(value: Any, total: int, problems: list[str]) -> dict[str, int]:
    """Percentages summing to 100, or counts summing to ``total``; returned as counts."""
    if not isinstance(value, dict):
        problems.append("difficulty must be a mapping like {easy: 20, medium: 50, hard: 30}")
        return {}
    unknown = sorted(set(value) - set(DIFFICULTIES))
    if unknown:
        problems.append(f"unknown difficulty {unknown}; choose from {', '.join(DIFFICULTIES)}")
    shares: dict[str, float] = {}
    for name in DIFFICULTIES:
        v = value.get(name, 0)
        if not isinstance(v, int | float) or isinstance(v, bool) or v < 0:
            problems.append(f"difficulty.{name} must be a number >= 0, not {v!r}")
            return {}
        if v:
            shares[name] = float(v)
    added = sum(shares.values())
    if math.isclose(added, 100):
        if total:
            return apportion(total, shares)
        return {}
    if total and math.isclose(added, total) and all(v.is_integer() for v in shares.values()):
        return {k: int(v) for k, v in shares.items()}
    problems.append(
        f"difficulty adds up to {added:g}; give percentages that sum to 100"
        + (f" or counts that sum to the {total} questions" if total else "")
    )
    return {}


def _list(value: Any, key: str, problems: list[str]) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        problems.append(f"{key} must be a list")
        return []
    return value


def _names(value: Any, key: str, problems: list[str]) -> list[str]:
    items = _list(value, key, problems)
    if any(not isinstance(i, str) or not i.strip() for i in items):
        problems.append(f"{key} must be a list of concept names")
        return []
    return [i.strip() for i in items]


def apportion(total: int, weights: dict[str, float]) -> dict[str, int]:
    """Split ``total`` in proportion to ``weights`` (largest remainder; ties keep dict order).

    Exact arithmetic, so no key ever gets more than its share rounded up. Keys whose share
    rounds to zero are left out.
    """
    fractions = {k: Fraction(w) for k, w in weights.items()}
    added = sum(fractions.values())
    if total <= 0 or added <= 0:
        return {}
    exact = {k: total * w / added for k, w in fractions.items()}
    counts = {k: math.floor(v) for k, v in exact.items()}
    order = sorted(exact, key=lambda k: -(exact[k] - counts[k]))  # stable: ties keep dict order
    for k in order[: total - sum(counts.values())]:
        counts[k] += 1
    return {k: n for k, n in counts.items() if n}
