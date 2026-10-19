"""Challenger loop: a disagreement about a concept's level produces one probe, never an average.

A challenge is queued when the Analyzer proposes a jump of two or more levels (``needs_challenge``),
or when the tutor's end-of-session estimate and the Analyzer's finding differ by two or more.
The next tutor session on that course opens with it: the ``challenger`` persona asks one question,
the learner answers, and the Analyzer grades that exchange alone, on a different provider.
Grading writes evidence and resolves the challenge; it never queues another (principle 7). A probe
resolved in the learner's favour applies the Analyzer's full proposed level (BL-040, P72).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from core.analysis.analyzer import (
    STRENGTH_CONFIDENCE,
    AnalysisError,
    AnalysisReport,
    Analyzer,
    LevelChange,
)
from core.context.compiler import ContextCompiler, Turn, TutorSession
from core.ledger.ledger import estimate_tokens, utcnow
from core.memory.learner import Concept, LearnerMemory, SessionRow
from core.memory.schema import EVIDENCE_STRENGTHS
from core.personas import load, render
from core.providers.models.base import TaskPackage
from core.router.router import Router

log = logging.getLogger(__name__)

DISAGREEMENT = 2  # levels apart before a probe is worth asking
ESTIMATE_TURNS_CAP = 1500  # tokens of the session shown to the tutor for its estimate
EXCERPTS = 3  # the learner's latest words on the concept shown to the Challenger

ESTIMATE_SYSTEM = """You tutored the session below. Estimate the learner's mastery of each concept
that came up, on this scale: 0 unseen, 1 exposed, 2 explained, 3 applied, 4 transferred,
5 retained. Reply with ONE line only, in the form `Concept name: level; Concept name: level`,
using names from the list you are given. Leave out concepts that didn't come up."""


@dataclass
class Challenge:
    id: int
    concept_id: str
    session_id: str | None
    reason: str
    question: str | None
    status: str
    created_at: str
    proposed_level: int | None = None  # the Analyzer's jump; None when raised by an estimate
    evidence_ids: str = "[]"  # JSON: the evidence behind that proposal


class ChallengeStore:
    """The ``challenges`` table. At most one open (unresolved) challenge per concept."""

    def __init__(self, conn: sqlite3.Connection, now: Callable[[], str] = utcnow) -> None:
        self.conn = conn
        self._now = now

    def queue(
        self,
        concept_id: str,
        session_id: str | None,
        reason: str,
        proposed_level: int | None = None,
        evidence_ids: list[str] | tuple[str, ...] = (),
    ) -> Challenge:
        """A new pending challenge, or the concept's open one with ``reason`` merged in.

        ``proposed_level`` is the Analyzer's jump (the latest one wins when merging);
        ``evidence_ids`` are the rows behind it (merged as a union).
        """
        existing = self.open_for_concept(concept_id)
        if existing is not None:
            if reason not in existing.reason.split("; "):
                existing.reason = f"{existing.reason}; {reason}"
            if proposed_level is not None:
                existing.proposed_level = proposed_level
            merged = list(dict.fromkeys([*json.loads(existing.evidence_ids), *evidence_ids]))
            existing.evidence_ids = json.dumps(merged)
            with self.conn:
                self.conn.execute(
                    "UPDATE challenges SET reason = ?, proposed_level = ?, evidence_ids = ?"
                    " WHERE id = ?",
                    (existing.reason, existing.proposed_level, existing.evidence_ids, existing.id),
                )
            return existing
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO challenges (concept_id, session_id, reason, status, created_at,"
                " proposed_level, evidence_ids) VALUES (?, ?, ?, 'pending', ?, ?, ?)",
                (
                    concept_id,
                    session_id,
                    reason,
                    self._now(),
                    proposed_level,
                    json.dumps(list(evidence_ids)),
                ),
            )
        challenge = self.get(cursor.lastrowid)
        assert challenge is not None
        return challenge

    def get(self, challenge_id: int) -> Challenge | None:
        row = self.conn.execute("SELECT * FROM challenges WHERE id = ?", (challenge_id,)).fetchone()
        return Challenge(**dict(row)) if row else None

    def open_for_concept(self, concept_id: str) -> Challenge | None:
        row = self.conn.execute(
            "SELECT * FROM challenges WHERE concept_id = ? AND status != 'resolved'"
            " ORDER BY id LIMIT 1",
            (concept_id,),
        ).fetchone()
        return Challenge(**dict(row)) if row else None

    def open_for_course(self, course: str) -> list[Challenge]:
        """Unresolved challenges on ``course``'s concepts, oldest first."""
        rows = self.conn.execute(
            "SELECT ch.* FROM challenges ch JOIN concepts c ON c.concept_id = ch.concept_id"
            " WHERE c.course = ? AND ch.status != 'resolved' ORDER BY ch.id",
            (course,),
        )
        return [Challenge(**dict(r)) for r in rows]

    def all(self, concept_id: str | None = None) -> list[Challenge]:
        sql, args = "SELECT * FROM challenges", []
        if concept_id is not None:
            sql += " WHERE concept_id = ?"
            args.append(concept_id)
        return [Challenge(**dict(r)) for r in self.conn.execute(sql + " ORDER BY id", args)]

    def mark(self, challenge: Challenge, status: str, question: str | None = None) -> None:
        challenge.status = status
        if question is not None:
            challenge.question = question
        with self.conn:
            self.conn.execute(
                "UPDATE challenges SET status = ?, question = ? WHERE id = ?",
                (challenge.status, challenge.question, challenge.id),
            )


# -- deciding what to challenge ------------------------------------------------------------


@dataclass(frozen=True)
class Disagreement:
    concept_id: str
    reason: str
    proposed_level: int | None  # the Analyzer's jump; None for a tutor-estimate disagreement


def disagreements(
    report: AnalysisReport, tutor_estimate: dict[str, int] | None = None
) -> list[Disagreement]:
    """Every disagreement of ``DISAGREEMENT`` levels or more."""
    found = [
        Disagreement(c.concept_id, f"analyzer proposed {c.current} -> {c.proposed}", c.proposed)
        for c in report.needs_challenge
        if abs(c.proposed - c.current) >= DISAGREEMENT
    ]
    for concept_id, estimate in (tutor_estimate or {}).items():
        finding = report.proposals.get(concept_id)
        if finding is not None and abs(estimate - finding) >= DISAGREEMENT:
            reason = f"tutor estimated {estimate}, analyzer found {finding}"
            found.append(Disagreement(concept_id, reason, None))
    return found


def queue_challenges(
    store: ChallengeStore,
    report: AnalysisReport,
    tutor_estimate: dict[str, int] | None = None,
) -> list[Challenge]:
    """Queue one challenge per disagreeing concept (collapsing into any open one)."""
    queued: dict[int, Challenge] = {}
    for d in disagreements(report, tutor_estimate):
        challenge = store.queue(
            d.concept_id,
            report.session_id,
            d.reason,
            d.proposed_level,
            report.support.get(d.concept_id, []),
        )
        queued[challenge.id] = challenge
    return list(queued.values())


# -- the tutor's end-of-session estimate ----------------------------------------------------


def estimate_task(course: str, concepts: list[Concept], turns: list[Turn]) -> TaskPackage:
    listed = "\n".join(f"- {c.name}" for c in concepts)
    session = "\n".join(f"{t.role.capitalize()}: {t.text.strip()}" for t in turns)
    if estimate_tokens(session) > ESTIMATE_TURNS_CAP:
        session = "…" + session[-ESTIMATE_TURNS_CAP * 4 :]  # keep the end of a long session
    user = f"## Concepts in {course}\n{listed}\n\n## The session\n{session}"
    return TaskPackage("tutor_estimate", None, ESTIMATE_SYSTEM, user, 100, {"course": course})


def parse_estimate(text: str, concepts: list[Concept]) -> dict[str, int]:
    """``Name: 3; Other name: 1`` -> {concept_id: level}; unknown names and bad levels dropped."""
    by_name = {c.name.lower(): c.concept_id for c in concepts}
    estimate: dict[str, int] = {}
    for name, level in re.findall(r"([^:;\n]+?)\s*:\s*([0-5])\b", text):
        concept_id = by_name.get(name.strip(" -*`\"'").lower())
        if concept_id is not None:
            estimate[concept_id] = int(level)
    return estimate


def format_estimate(estimate: dict[str, int], concepts: list[Concept]) -> str:
    names = {c.concept_id: c.name for c in concepts}
    return "; ".join(f"{names[cid]}: {level}" for cid, level in estimate.items())


# -- running a probe ------------------------------------------------------------------------


@dataclass
class Probe:
    challenge: Challenge
    concept: Concept
    question: str
    provider: str | None  # who wrote the question; None when it was asked in an earlier session


class ChallengeRunner:
    """Asks a challenge's question (``challenger`` persona) and grades the answer (Analyzer)."""

    def __init__(
        self,
        store: ChallengeStore,
        learner: LearnerMemory,
        question_router: Router,
        analyzer: Analyzer,
        compiler: ContextCompiler | None = None,
    ) -> None:
        self.store = store
        self._learner = learner
        self._router = question_router
        self._analyzer = analyzer
        self._compiler = compiler

    def pending(self, course: str) -> list[Challenge]:
        return self.store.open_for_course(course)

    def ask(self, challenge: Challenge, session: TutorSession) -> Probe:
        """The probe's question: the stored one if it was already asked, else a new one."""
        concept = self._learner.get_concept(challenge.concept_id)
        assert concept is not None, challenge.concept_id
        if challenge.question and challenge.status != "pending":
            self.store.mark(challenge, "asked")
            return Probe(challenge, concept, challenge.question, None)
        result = self._router.run(self._question_task(challenge, concept, session))
        question = result.text.strip()
        self.store.mark(challenge, "asked", question)
        return Probe(challenge, concept, question, result.provider)

    def grade(self, probe: Probe, answer: str, row: SessionRow) -> AnalysisReport:
        """Grade the exchange alone, apply the outcome, and resolve the challenge (BL-040, P72).

        In the learner's favour (the grade proposes the challenged level or more, for a jump
        upward): mastery is set to the Analyzer's full proposed level, citing the original
        evidence plus this exchange's, ``changed_by="challenger"``. Otherwise the exchange's
        evidence is all that's written and no level changes. Never an average. A challenge
        raised only by the tutor's estimate never changes a level. If grading itself fails,
        the challenge goes back to ``asked`` so the same question is asked next session.
        """
        self.store.mark(probe.challenge, "answered")
        transcript = (
            f"**Tutor (challenger · {probe.provider or 'earlier session'}):** {probe.question}\n\n"
            f"**Learner:** {answer}\n"
        )
        exclude = {probe.provider} if probe.provider else set()
        try:
            report = self._analyzer.grade_exchange(row, probe.concept, transcript, exclude)
        except AnalysisError:
            self.store.mark(probe.challenge, "asked")
            raise
        self._apply_outcome(probe, report)
        self.store.mark(probe.challenge, "resolved")
        return report

    def _apply_outcome(self, probe: Probe, report: AnalysisReport) -> None:
        challenge, concept_id = probe.challenge, probe.concept.concept_id
        mastery = self._learner.get_mastery(concept_id)
        current = mastery.level if mastery else 0
        target = challenge.proposed_level
        graded = report.proposals.get(concept_id)
        upheld = (
            target is not None
            and target > current
            and graded is not None
            and graded >= target
            and bool(report.evidence_ids)
        )
        if not upheld:
            return
        exchange = [
            e for e in self._learner.evidence(concept_id) if e.evidence_id in report.evidence_ids
        ]
        strongest = max((e.strength for e in exchange), key=EVIDENCE_STRENGTHS.index)
        cited = list(dict.fromkeys([*json.loads(challenge.evidence_ids), *report.evidence_ids]))
        self._learner.set_mastery(
            concept_id, target, STRENGTH_CONFIDENCE[strongest], cited, changed_by="challenger"
        )
        report.applied.append(LevelChange(concept_id, current, target))

    def _question_task(
        self, challenge: Challenge, concept: Concept, session: TutorSession
    ) -> TaskPackage:
        mastery = self._learner.get_mastery(concept.concept_id)
        level = mastery.level if mastery else 0
        said = [e.excerpt_ref for e in self._learner.evidence(concept.concept_id) if e.excerpt_ref]
        excerpts = "\n".join(f"- {s}" for s in said[-EXCERPTS:]) or "(nothing recorded yet)"
        source = "(not retrieved)"
        if self._compiler is not None:
            source = self._compiler.ground(concept.name, session.course, session)
        user = (
            f"## Concept\n{concept.name} (recorded mastery: level {level}/5)\n\n"
            f"## Why it's being challenged\n{challenge.reason}\n\n"
            f"## The learner's recent words on it\n{excerpts}\n\n"
            f"## Course sources (grounded in NotebookLM)\n{source}\n\n"
            "Write the one probe now."
        )
        system = render(load("challenger"), {"course": session.course})
        return TaskPackage(
            "question_gen",
            "challenger",
            system,
            user,
            300,
            {"course": session.course, "concepts": [concept.concept_id]},
        )
