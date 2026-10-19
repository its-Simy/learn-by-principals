"""Coverage Planner: an ExamSpec plus the learner's mastery -> how many questions per concept.

Selection: the course's concepts in the spec's weeks, minus ``exclude``, plus ``include``.
Weights by mode:

- ``realistic``: every week weighs the same, split evenly among its concepts
- ``weakness``: ∝ (5 − level), floored so a mastered concept still gets a share
- ``challenge``: only concepts at level 3+, evenly; their questions are tagged ``transfer``
- ``diagnostic``: ∝ (1 − confidence), floored, so the least certain concepts weigh most

Questions are apportioned by largest remainder, then each concept's questions are split across
formats and difficulties so every column still sums to the spec's totals.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.exams.spec import ExamSpec, apportion
from core.memory.db import slug
from core.memory.learner import Concept, Mastery

WEAKNESS_FLOOR = 0.5
DIAGNOSTIC_FLOOR = 0.1
CHALLENGE_MIN_LEVEL = 3
TRANSFER_LEVEL = 4


class PlanError(Exception):
    pass


@dataclass(frozen=True)
class PlanRow:
    concept: Concept
    n_questions: int
    difficulty_mix: dict[str, int]
    format_mix: dict[str, int]
    weight: float
    level: int = 0
    tags: tuple[str, ...] = ()  # ("transfer",) in challenge mode

    @property
    def target_level(self) -> int:
        """The mastery level the questions should test (the Questioner's level tag)."""
        if "transfer" in self.tags:
            return TRANSFER_LEVEL
        return min(max(self.level + 1, 2), TRANSFER_LEVEL)


@dataclass
class CoveragePlan:
    spec: ExamSpec
    rows: list[PlanRow]
    unmatched_include: list[str] = field(default_factory=list)
    unmatched_exclude: list[str] = field(default_factory=list)
    no_week: list[str] = field(default_factory=list)  # concepts left out: no week recorded

    @property
    def total(self) -> int:
        return sum(r.n_questions for r in self.rows)

    def format_totals(self) -> dict[str, int]:
        return _column_totals(r.format_mix for r in self.rows)

    def difficulty_totals(self) -> dict[str, int]:
        return _column_totals(r.difficulty_mix for r in self.rows)


def matches(concept: Concept, name: str) -> bool:
    """A spec name refers to a concept by its name (any case/punctuation) or its id."""
    return slug(concept.name) == slug(name) or concept.concept_id == name.strip().lower()


def plan(spec: ExamSpec, concepts: list[Concept], mastery: dict[str, Mastery]) -> CoveragePlan:
    course = [c for c in concepts if c.course == spec.course]
    unmatched_include = [n for n in spec.include if not any(matches(c, n) for c in course)]
    unmatched_exclude = [n for n in spec.exclude if not any(matches(c, n) for c in course)]

    def excluded(c: Concept) -> bool:
        return any(matches(c, n) for n in spec.exclude)

    if spec.weeks:
        base = [c for c in course if c.week in spec.weeks and not excluded(c)]
        no_week = [c.name for c in course if c.week is None and not excluded(c)]
    else:
        base, no_week = [c for c in course if not excluded(c)], []
    extras = [
        c
        for c in course
        if c not in base and not excluded(c) and any(matches(c, n) for n in spec.include)
    ]
    no_week = [n for n in no_week if n not in {c.name for c in extras}]

    def level(c: Concept) -> int:
        m = mastery.get(c.concept_id)
        return m.level if m else 0

    selected = base + extras
    if spec.mode == "challenge":
        selected = [c for c in selected if level(c) >= CHALLENGE_MIN_LEVEL]
    if not selected:
        detail = (
            f"no {spec.course} concept at level {CHALLENGE_MIN_LEVEL}+"
            if spec.mode == "challenge" and (base or extras)
            else f"no {spec.course} concept matches weeks {list(spec.weeks) or 'any'}"
        )
        raise PlanError(f"Nothing to plan for {spec.exam}: {detail}")

    weights = _weights(spec, selected, [c for c in extras if c in selected], mastery)
    # Heaviest first; ties by week then name, so apportioning is deterministic.
    ordered = sorted(
        selected, key=lambda c: (-weights[c.concept_id], c.week or 10**6, c.name.lower())
    )
    counts = apportion(spec.total_questions, {c.concept_id: weights[c.concept_id] for c in ordered})
    chosen = sorted(
        (c for c in ordered if counts.get(c.concept_id)),
        key=lambda c: (-counts[c.concept_id], c.week or 10**6, c.name.lower()),
    )
    ns = [counts[c.concept_id] for c in chosen]
    formats = _spread(ns, spec.formats)
    difficulties = _spread(ns, spec.difficulty)
    tags = ("transfer",) if spec.mode == "challenge" else ()
    rows = [
        PlanRow(c, n, d, f, weights[c.concept_id], level(c), tags)
        for c, n, f, d in zip(chosen, ns, formats, difficulties, strict=True)
    ]
    return CoveragePlan(spec, rows, unmatched_include, unmatched_exclude, no_week)


def _weights(
    spec: ExamSpec, selected: list[Concept], extras: list[Concept], mastery: dict[str, Mastery]
) -> dict[str, float]:
    if spec.mode == "weakness":
        return {c.concept_id: max(5 - _level(mastery, c), WEAKNESS_FLOOR) for c in selected}
    if spec.mode == "diagnostic":
        return {c.concept_id: max(1 - _confidence(mastery, c), DIAGNOSTIC_FLOOR) for c in selected}
    if spec.mode == "challenge":
        return {c.concept_id: 1.0 for c in selected}
    # realistic: each week weighs 1, split among its concepts; concepts added by `include`
    # from outside the weeks get the average weight.
    in_weeks = [c for c in selected if c not in extras]
    per_week: dict[int | None, int] = {}
    for c in in_weeks:
        per_week[c.week] = per_week.get(c.week, 0) + 1
    weights = {c.concept_id: 1 / per_week[c.week] for c in in_weeks}
    mean = sum(weights.values()) / len(weights) if weights else 1.0
    weights.update({c.concept_id: mean for c in extras})
    return weights


def _level(mastery: dict[str, Mastery], c: Concept) -> int:
    m = mastery.get(c.concept_id)
    return m.level if m else 0


def _confidence(mastery: dict[str, Mastery], c: Concept) -> float:
    m = mastery.get(c.concept_id)
    return m.confidence if m else 0.0


def _spread(row_sizes: list[int], totals: dict[str, int]) -> list[dict[str, int]]:
    """Split each row's size across ``totals``' columns so rows and columns both sum exactly.

    Each row takes its share of what's left in every column, so later rows can never be short.
    """
    remaining = dict(totals)
    mixes = []
    for n in row_sizes:
        mix = apportion(n, {k: v for k, v in remaining.items() if v})
        for k, v in mix.items():
            remaining[k] -= v
        mixes.append(mix)
    return mixes


def _column_totals(mixes) -> dict[str, int]:
    totals: dict[str, int] = {}
    for mix in mixes:
        for k, v in mix.items():
            totals[k] = totals.get(k, 0) + v
    return totals
