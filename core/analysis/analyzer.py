"""Analyzer v0: after a session, a different model reads the transcript and emits evidence.

Principle 6: the Analyzer never runs on a provider that tutored the session.
Principle 4: every mastery change it makes points at the evidence rows written for it.
A proposed level exactly one away from the level at session start is applied; bigger jumps are
recorded as ``needs_challenge`` and not applied (``core.analysis.challenge`` queues a probe).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from core.jsonutil import extract_json_array
from core.ledger.ledger import estimate_tokens
from core.memory.learner import Concept, LearnerError, LearnerMemory, SessionRow
from core.memory.schema import EVIDENCE_STRENGTHS, EVIDENCE_TYPES
from core.memory.vault import Vault
from core.personas import load, render
from core.providers.models.base import ModelError, TaskPackage
from core.router.router import Router

log = logging.getLogger(__name__)

TRANSCRIPT_CAP = 6000
STRENGTH_CONFIDENCE = {"weak": 0.4, "moderate": 0.6, "strong": 0.8}

# Learner turns in a core.tutor transcript: "**Learner:** …" up to the next tutor line or note.
_LEARNER_TURN = re.compile(r"\*\*Learner:\*\*\s*(.*?)(?=\n\*\*Tutor|\n_|\Z)", re.DOTALL)


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def learner_words(transcript: str) -> str:
    return _normalise(" ".join(_LEARNER_TURN.findall(transcript)))


def excerpt_is_learners(excerpt: str, learner_text: str) -> bool:
    """The excerpt, minus a "Learner:" label, quotes and ellipses, occurs in the learner's turns."""
    text = re.sub(r"^\s*(\*\*)?learner:?(\*\*)?\s*", "", excerpt.strip(), flags=re.IGNORECASE)
    text = _normalise(text.strip(" \"'“”‘’").strip("…").strip("."))
    return bool(text) and text in learner_text


class AnalysisError(Exception):
    pass


@dataclass(frozen=True)
class LevelChange:
    concept_id: str
    current: int
    proposed: int


@dataclass
class AnalysisReport:
    session_id: str
    provider: str
    evidence_ids: list[str] = field(default_factory=list)
    applied: list[LevelChange] = field(default_factory=list)
    needs_challenge: list[LevelChange] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    # The Analyzer's finding: the last valid proposed level per concept it wrote evidence for.
    proposals: dict[str, int] = field(default_factory=dict)
    excerpts_checked: int = 0
    excerpts_verified: int = 0
    # Evidence ids behind each needs_challenge proposal (a challenge keeps them, BL-040).
    support: dict[str, list[str]] = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"Analyzer ({self.provider}): {len(self.evidence_ids)} evidence, "
            f"{len(self.applied)} mastery change(s), "
            f"{len(self.needs_challenge)} need a Challenger probe"
            + (f", {len(self.skipped)} item(s) skipped" if self.skipped else "")
            + "."
        )


def apply_proposal(
    learner: LearnerMemory,
    report: AnalysisReport,
    concept_id: str,
    current: int,
    proposed: int,
    confidence: float,
    evidence_ids: list[str],
) -> None:
    """The Analyzer's rule for a proposed level: exactly one level from ``current`` is applied
    (``set_mastery`` citing ``evidence_ids``); two or more is recorded as ``needs_challenge``."""
    change = LevelChange(concept_id, current, proposed)
    if 0 <= proposed <= 5:
        report.proposals[concept_id] = proposed
    if abs(proposed - current) == 1 and 0 <= proposed <= 5:
        learner.set_mastery(concept_id, proposed, confidence, evidence_ids, changed_by="analyzer")
        report.applied = [c for c in report.applied if c.concept_id != concept_id]
        report.applied.append(change)
    elif abs(proposed - current) > 1:
        report.needs_challenge.append(change)
        report.support[concept_id] = list(evidence_ids)


def tutor_providers(row: SessionRow) -> set[str]:
    return {p for p in (row.tutor_provider or "").split(",") if p}


class Analyzer:
    def __init__(self, router: Router, learner: LearnerMemory, vault: Vault | None = None) -> None:
        self._router = router
        self._learner = learner
        self._vault = vault

    def analyze(
        self, row: SessionRow, transcript: str, tutor_estimate: str | None = None
    ) -> AnalysisReport:
        """Analyze a whole session; ``tutor_estimate`` (one line) goes into its summary."""
        concepts = self._learner.concepts(row.course)
        report = self._run(row, transcript, concepts, tutor_providers(row))

        row.analyzer_provider = report.provider
        if self._vault is not None:
            ids = set(report.evidence_ids)
            evidence = [
                e
                for c in concepts
                for e in self._learner.evidence(c.concept_id)
                if e.evidence_id in ids
            ]
            extra = {"tutor_estimate": tutor_estimate} if tutor_estimate else None
            row.summary_path = str(
                self._vault.write_session_summary(row, self._summary_text(report), evidence, extra)
            )
        self._learner.update_session(row)
        for change in report.needs_challenge:
            log.warning(
                "needs_challenge: %s proposed %d -> %d (not applied)",
                change.concept_id,
                change.current,
                change.proposed,
            )
        return report

    def grade_exchange(
        self, row: SessionRow, concept: Concept, transcript: str, exclude: set[str]
    ) -> AnalysisReport:
        """Grade one short exchange (a Challenger probe and its answer) for one concept alone.

        Evidence is written and proposals are reported, but mastery is never changed here: the
        Challenger decides what the result means (BL-040). The session row and summary are left
        alone; ``exclude`` keeps the provider that asked the question from grading it.
        """
        return self._run(row, transcript, [concept], exclude, apply=False)

    def _run(
        self,
        row: SessionRow,
        transcript: str,
        concepts: list[Concept],
        exclude: set[str],
        apply: bool = True,
    ) -> AnalysisReport:
        by_name = {c.name.lower(): c for c in concepts} | {c.concept_id: c for c in concepts}
        start_levels = {
            c.concept_id: (m.level if (m := self._learner.get_mastery(c.concept_id)) else 0)
            for c in concepts
        }
        task = self._task(row, transcript, concepts, start_levels)
        try:
            result = self._router.run(task, exclude=exclude)
        except ModelError as exc:
            raise AnalysisError(f"Analyzer could not run: {exc}") from exc
        items = extract_json_array(result.text)
        if items is None:
            raise AnalysisError(f"Analyzer output isn't a JSON array: {result.text[:200]}")

        report = AnalysisReport(row.session_id, result.provider)
        support: dict[str, list[str]] = {}
        spoken = learner_words(transcript)
        for item in items:
            self._apply_item(
                item, row, result.provider, by_name, start_levels, support, report, spoken, apply
            )
        if report.excerpts_checked:
            # Groundedness: the share of excerpts that really are the learner's words (P64).
            self._router.benchmarks.record(
                result.provider,
                task.task_type,
                groundedness=report.excerpts_verified / report.excerpts_checked,
            )
        return report

    def _task(self, row, transcript, concepts, start_levels) -> TaskPackage:
        mastery = (
            "\n".join(f"- {c.name}: level {start_levels[c.concept_id]}" for c in concepts)
            or "(no concepts seeded for this course)"
        )
        text = transcript
        if estimate_tokens(text) > TRANSCRIPT_CAP:
            text = "…" + text[-TRANSCRIPT_CAP * 4 :]  # keep the end of a very long session
        user = (
            f"## Concepts and current mastery\n{mastery}\n\n"
            f"## Transcript of session {row.session_id}\n{text}"
        )
        system = render(load("analyzer"), {"course": row.course})
        return TaskPackage(
            "analyze_transcript", "analyzer", system, user, 1500, {}, output_format="json"
        )

    def _apply_item(
        self, item, row, provider, by_name, start_levels, support, report, spoken, apply=True
    ) -> None:
        if not isinstance(item, dict):
            report.skipped.append(f"not an object: {item!r}"[:120])
            return
        concept = by_name.get(str(item.get("concept", "")).strip().lower())
        kind, strength = item.get("evidence_type"), item.get("strength")
        if concept is None:
            report.skipped.append(f"unknown concept {item.get('concept')!r}")
            return
        if kind not in EVIDENCE_TYPES or strength not in EVIDENCE_STRENGTHS:
            report.skipped.append(f"{concept.name}: bad type/strength {kind!r}/{strength!r}")
            return
        # Evidence is append-only, so an unverifiable excerpt is never written (P64).
        report.excerpts_checked += 1
        if not excerpt_is_learners(str(item.get("excerpt") or ""), spoken):
            report.skipped.append(f"{concept.name}: excerpt is not in the learner's own turns")
            return
        report.excerpts_verified += 1
        try:
            evidence_id = self._learner.add_evidence(
                concept.concept_id,
                kind,
                strength,
                session_id=row.session_id,
                source_provider=provider,
                excerpt_ref=str(item.get("excerpt") or "")[:500] or None,
            )
        except LearnerError as exc:
            report.skipped.append(str(exc))
            return
        report.evidence_ids.append(evidence_id)
        support.setdefault(concept.concept_id, []).append(evidence_id)

        try:
            proposed = int(item.get("proposed_level"))
        except (TypeError, ValueError):
            return
        if not apply:
            if 0 <= proposed <= 5:
                report.proposals[concept.concept_id] = proposed
            return
        apply_proposal(
            self._learner,
            report,
            concept.concept_id,
            start_levels[concept.concept_id],
            proposed,
            STRENGTH_CONFIDENCE[strength],
            support[concept.concept_id],
        )

    @staticmethod
    def _summary_text(report: AnalysisReport) -> str:
        lines = [report.summary()]
        for c in report.applied:
            lines.append(f"- applied: {c.concept_id} {c.current} -> {c.proposed}")
        for c in report.needs_challenge:
            lines.append(f"- needs_challenge: {c.concept_id} {c.current} -> {c.proposed}")
        for s in report.skipped:
            lines.append(f"- skipped: {s}")
        return "\n".join(lines)
