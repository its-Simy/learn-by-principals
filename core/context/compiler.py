"""Context Compiler v0: a question -> a small TaskPackage (principle 3: retrieve selectively).

1. intent: keyword match of the question against the course's concept names
2. source context: NotebookLM's grounded answer + citations (<= 1,200 tokens)
3. learner context: mastery rows + misconceptions for the matched concepts (<= 600 tokens)
4. the persona, rendered as the system prompt
5. session context: the last 6 turns (<= 800 tokens)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from core.ledger.ledger import estimate_tokens
from core.memory.db import Manifest
from core.memory.learner import Concept, LearnerMemory
from core.personas import Persona, load, render
from core.providers.knowledge.base import Conversation, KnowledgeError, KnowledgeProvider
from core.providers.models.base import TaskPackage

log = logging.getLogger(__name__)

SOURCE_CAP = 1200
LEARNER_CAP = 600
SESSION_CAP = 800
QUESTION_CAP = 400
RECENT_TURNS = 6
MAX_ANCHORS = 5
MAX_OUTPUT_TOKENS = 800

_STOPWORDS = frozenset(
    "a an and are as at be by does do for from how i in is it of on or the to what when"
    " where which why with vs".split()
)


@dataclass
class Turn:
    role: str  # "learner" | "tutor"
    text: str


@dataclass
class TutorSession:
    session_id: str
    course: str
    turns: list[Turn] = field(default_factory=list)
    # One NotebookLM conversation per tutor session, so follow-ups ("why?") keep their context.
    conversation: Conversation = field(default_factory=Conversation)


def truncate_tokens(text: str, cap: int) -> str:
    if estimate_tokens(text) <= cap:
        return text
    return text[: max(cap * 4 - 1, 0)].rstrip() + "…"


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words} - _STOPWORDS


def match_concepts(question: str, concepts: list[Concept]) -> list[Concept]:
    """Concepts whose every significant name word appears in the question (v0 intent)."""
    asked = _tokens(question)
    scored = []
    for concept in concepts:
        needed = _tokens(concept.name)
        if needed and needed <= asked:
            scored.append((len(needed), concept))
    return [c for _, c in sorted(scored, key=lambda s: (-s[0], s[1].name))]


class ContextCompiler:
    def __init__(
        self,
        knowledge: KnowledgeProvider,
        learner: LearnerMemory,
        manifest: Manifest | None = None,
    ) -> None:
        self._knowledge = knowledge
        self._learner = learner
        self._manifest = manifest

    def compile(
        self,
        question: str,
        course: str,
        persona: str | Persona,
        session: TutorSession | None = None,
    ) -> TaskPackage:
        persona = load(persona) if isinstance(persona, str) else persona
        concepts = match_concepts(question, self._learner.concepts(course))
        system = render(persona, {"course": course, "anchors": self.anchors(course)})
        conversation = session.conversation if session else None
        source = truncate_tokens(self._source_context(question, course, conversation), SOURCE_CAP)
        learner = truncate_tokens(self._learner_context(concepts), LEARNER_CAP)
        recent = self._session_context(session)
        asked = truncate_tokens(question, QUESTION_CAP)

        sections = [
            ("Course sources (grounded in NotebookLM)", source),
            ("What this learner has shown", learner),
            ("Recent conversation", recent),
            ("Learner's question", asked),
        ]
        user = "\n\n".join(f"## {title}\n{body or '(none)'}" for title, body in sections)
        report = {
            "persona": estimate_tokens(system),
            "source": estimate_tokens(source),
            "learner": estimate_tokens(learner),
            "session": estimate_tokens(recent),
            "question": estimate_tokens(asked),
        }
        report["total"] = estimate_tokens(system) + estimate_tokens(user)
        return TaskPackage(
            task_type=persona.task_types[0],
            persona=persona.name,
            system=system,
            user=user,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            metadata={
                "context_report": report,
                "course": course,
                "concepts": [c.concept_id for c in concepts],
                "session_id": session.session_id if session else None,
            },
        )

    def ground(self, question: str, course: str, session: TutorSession) -> str:
        """A grounded answer with citations, asked in the session's own conversation (``/ask``)."""
        return self._source_context(question, course, session.conversation)

    # -- sections ----------------------------------------------------------------------------

    def _source_context(self, question: str, course: str, conversation: Conversation | None) -> str:
        try:
            notebook_id = self._knowledge.ensure_notebook(course)
            answer = self._knowledge.query(notebook_id, question, conversation=conversation)
        except KnowledgeError as exc:
            log.warning("No source context for %s: %s", course, exc)
            return f"(course sources unavailable: {exc})"
        titles = {}
        if self._manifest is not None:
            titles = {
                r.notebook_source_id: r.filename or r.title
                for r in self._manifest.all(course)
                if r.notebook_source_id
            }
        cited = "\n".join(
            f"[{n}] {titles.get(c.source_id, c.source_id)}: {' '.join(c.excerpt.split())[:240]}"
            for n, c in enumerate(answer.citations, start=1)
        )
        cited = truncate_tokens(cited, SOURCE_CAP // 3)
        # The answer gives way before the citations do.
        room = SOURCE_CAP - estimate_tokens(cited) - 1
        return "\n".join(p for p in (truncate_tokens(answer.text.strip(), room), cited) if p)

    def _learner_context(self, concepts: list[Concept]) -> str:
        lines = []
        for concept in concepts:
            mastery = self._learner.get_mastery(concept.concept_id)
            if mastery is None:
                lines.append(f"- {concept.name}: no evidence yet (level 0)")
            else:
                retention = (
                    f", retention {mastery.retention_confidence:.2f}"
                    if mastery.retention_confidence is not None
                    else ""
                )
                lines.append(
                    f"- {concept.name}: level {mastery.level}/5, confidence"
                    f" {mastery.confidence:.2f}{retention}, {mastery.evidence_count} evidence"
                )
            for e in self._learner.evidence(concept.concept_id):
                if e.type == "misconception" and e.excerpt_ref:
                    lines.append(f"  - misconception: {e.excerpt_ref}")
        return "\n".join(lines)

    def _session_context(self, session: TutorSession | None) -> str:
        """The last turns, newest kept whole first; the oldest one kept may be cut short."""
        if session is None:
            return ""
        kept: list[str] = []
        budget = SESSION_CAP
        for turn in reversed(session.turns[-RECENT_TURNS:]):
            line = f"{turn.role.capitalize()}: {turn.text.strip()}"
            cost = estimate_tokens(line) + 1
            if cost > budget:
                if budget > 20:
                    kept.append(truncate_tokens(line, budget - 1))
                break
            kept.append(line)
            budget -= cost
        return "\n".join(reversed(kept))

    def anchors(self, course: str) -> list[dict]:
        """Concepts the learner has shown at level 3+, strongest first (for the Analogist)."""
        anchors = []
        for concept in self._learner.concepts(course):
            mastery = self._learner.get_mastery(concept.concept_id)
            if mastery and mastery.level >= 3:
                anchors.append({"concept": concept.name, "level": mastery.level})
        anchors.sort(key=lambda a: -a["level"])
        return anchors[:MAX_ANCHORS]
