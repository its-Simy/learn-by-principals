"""Analyzer v0: after a session, a different model reads the transcript and emits evidence.

Principle 6: the Analyzer never runs on a provider that tutored the session.
Principle 4: every mastery change it makes points at the evidence rows written for it.
A proposed level exactly one away from the level at session start is applied; bigger jumps are
recorded as ``needs_challenge`` for the Challenger (Phase 6+) and not applied.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from core.jsonutil import extract_json_array
from core.ledger.ledger import estimate_tokens
from core.memory.learner import LearnerError, LearnerMemory, SessionRow
from core.memory.schema import EVIDENCE_STRENGTHS, EVIDENCE_TYPES
from core.memory.vault import Vault
from core.personas import load, render
from core.providers.models.base import ModelError, TaskPackage
from core.router.router import Router

log = logging.getLogger(__name__)

TRANSCRIPT_CAP = 6000
STRENGTH_CONFIDENCE = {"weak": 0.4, "moderate": 0.6, "strong": 0.8}


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

    def summary(self) -> str:
        return (
            f"Analyzer ({self.provider}): {len(self.evidence_ids)} evidence, "
            f"{len(self.applied)} mastery change(s), "
            f"{len(self.needs_challenge)} need a Challenger probe"
            + (f", {len(self.skipped)} item(s) skipped" if self.skipped else "")
            + "."
        )


def tutor_providers(row: SessionRow) -> set[str]:
    return {p for p in (row.tutor_provider or "").split(",") if p}


class Analyzer:
    def __init__(self, router: Router, learner: LearnerMemory, vault: Vault | None = None) -> None:
        self._router = router
        self._learner = learner
        self._vault = vault

    def analyze(self, row: SessionRow, transcript: str) -> AnalysisReport:
        concepts = self._learner.concepts(row.course)
        by_name = {c.name.lower(): c for c in concepts} | {c.concept_id: c for c in concepts}
        start_levels = {
            c.concept_id: (m.level if (m := self._learner.get_mastery(c.concept_id)) else 0)
            for c in concepts
        }
        task = self._task(row, transcript, concepts, start_levels)
        try:
            result = self._router.run(task, exclude=tutor_providers(row))
        except ModelError as exc:
            raise AnalysisError(f"Analyzer could not run: {exc}") from exc
        items = extract_json_array(result.text)
        if items is None:
            raise AnalysisError(f"Analyzer output isn't a JSON array: {result.text[:200]}")

        report = AnalysisReport(row.session_id, result.provider)
        support: dict[str, list[str]] = {}
        for item in items:
            self._apply_item(item, row, result.provider, by_name, start_levels, support, report)

        row.analyzer_provider = result.provider
        if self._vault is not None:
            evidence = [
                e
                for c in concepts
                for e in self._learner.evidence(c.concept_id)
                if e.evidence_id in set(report.evidence_ids)
            ]
            row.summary_path = str(
                self._vault.write_session_summary(row, self._summary_text(report), evidence)
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
        return TaskPackage("analyze_transcript", "analyzer", system, user, 1500, {})

    def _apply_item(self, item, row, provider, by_name, start_levels, support, report) -> None:
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
        current = start_levels[concept.concept_id]
        change = LevelChange(concept.concept_id, current, proposed)
        if abs(proposed - current) == 1 and 0 <= proposed <= 5:
            self._learner.set_mastery(
                concept.concept_id,
                proposed,
                STRENGTH_CONFIDENCE[strength],
                support[concept.concept_id],
            )
            report.applied = [c for c in report.applied if c.concept_id != concept.concept_id]
            report.applied.append(change)
        elif abs(proposed - current) > 1:
            report.needs_challenge.append(change)

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
