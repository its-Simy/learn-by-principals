"""The chat pane: a live tutor session, grounded questions and past sessions."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

from api.errors import provider_failure
from core.analysis.challenge import Probe
from core.memory.db import ResourceRow
from core.memory.learner import SessionRow
from core.providers.knowledge.base import GroundedAnswer
from core.sessions import SessionState
from core.tutor import Tutor

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SessionStartIn(BaseModel):
    persona: str = "simplifier"


class TurnIn(BaseModel):
    """One line of the REPL: a question, or ``/persona x``, ``/rate n``, ``/skip``, ``/ask q``,
    ``/end``, ``/help``."""

    text: NonBlank


class AskIn(BaseModel):
    question: NonBlank
    # Only these NotebookLM sources (SourceOut.notebook_source_id); not inside a live session,
    # whose /ask always asks the whole notebook in the session's conversation.
    source_ids: list[str] | None = None


class MessageOut(BaseModel):
    role: Literal["learner", "tutor"]
    text: str


class ProbeOut(BaseModel):
    """A Challenger question waiting for its answer: the next turn's text answers it."""

    challenge_id: int
    concept_id: str
    concept: str
    question: str

    @classmethod
    def from_core(cls, probe: Probe) -> ProbeOut:
        return cls(
            challenge_id=probe.challenge.id,
            concept_id=probe.concept.concept_id,
            concept=probe.concept.name,
            question=probe.question,
        )


def _probe(tutor: Tutor) -> ProbeOut | None:
    return ProbeOut.from_core(tutor.probe) if tutor.probe is not None else None


class LiveSessionOut(BaseModel):
    """The tutor this server holds for a course. ``turns`` are the tutoring exchanges the
    tutor remembers; probes, ``/ask`` answers and command replies are in the transcript."""

    session_id: str
    persona: str
    started_at: str
    turns: list[MessageOut]
    probe: ProbeOut | None
    ended: bool
    ratable: bool  # there is an answer for ``/rate`` to rate

    @classmethod
    def from_core(cls, tutor: Tutor) -> LiveSessionOut:
        assert tutor.row is not None and tutor.session is not None, "call start() first"
        return cls(
            session_id=tutor.row.session_id,
            persona=tutor.persona,
            started_at=tutor.row.started_at,
            turns=[MessageOut(role=t.role, text=t.text) for t in tutor.session.turns],
            probe=_probe(tutor),
            ended=tutor.ended,
            ratable=tutor.last_answer is not None,
        )


class TurnErrorOut(BaseModel):
    """Why a line to the tutor got no answer, as a 502 body says it: the provider that failed
    last (None when none was tried, or the persona had no concept to build on) and, for a rate
    limit, the hint's reset time (e.g. ``3pm``)."""

    provider: str | None
    detail: str
    resets_at: str | None


class TurnOut(BaseModel):
    reply: str | None  # None for a line that needs no answer
    ended: bool
    persona: str
    probe: ProbeOut | None
    ratable: bool
    provider: str | None  # the provider that wrote this turn's tutoring answer, if it wrote one
    # Set when the line went to the tutor and no answer came back; ``reply`` is then the CLI's
    # "(no answer: …)" line.
    error: TurnErrorOut | None

    @classmethod
    def from_core(
        cls,
        tutor: Tutor,
        reply: str | None,
        answered: bool = False,
        error: Exception | None = None,
    ) -> TurnOut:
        """``answered``: this turn added a tutoring exchange, so ``last_answer`` is its own."""
        return cls(
            reply=reply,
            ended=tutor.ended,
            persona=tutor.persona,
            probe=_probe(tutor),
            ratable=tutor.last_answer is not None,
            provider=tutor.last_answer[0] if answered and tutor.last_answer else None,
            error=TurnErrorOut(**provider_failure(error)) if error is not None else None,
        )


class CitationOut(BaseModel):
    n: int  # the [n] the answer's text refers to
    source_id: str
    filename: str | None  # None when the source isn't in the manifest
    bucket: str | None
    excerpt: str


class AskOut(BaseModel):
    """A grounded answer and its citations. ``in_session``: asked in the live tutor session's
    own conversation (its ``/ask``), which always asks every source."""

    text: str
    citations: list[CitationOut]
    in_session: bool

    @classmethod
    def from_core(
        cls, answer: GroundedAnswer, sources: dict[str, ResourceRow], in_session: bool = False
    ) -> AskOut:
        """``sources`` maps a NotebookLM source id to its manifest row, as ``brightlearn ask``
        labels a citation ``filename (bucket)``."""
        citations = []
        for n, citation in enumerate(answer.citations, start=1):
            row = sources.get(citation.source_id)
            citations.append(
                CitationOut(
                    n=n,
                    source_id=citation.source_id,
                    filename=row.filename if row else None,
                    bucket=row.bucket if row else None,
                    excerpt=" ".join(citation.excerpt.split()),
                )
            )
        return cls(text=answer.text, citations=citations, in_session=in_session)


class SessionOut(BaseModel):
    """A ``sessions`` row. ``stale`` is still open (it blocks its course) but idle long enough
    to offer closing; ``live`` is set while this server holds its tutor (end it, don't close)."""

    session_id: str
    course: str
    started_at: str
    ended_at: str | None
    last_turn_at: str | None
    tutor_provider: str | None
    analyzer_provider: str | None
    state: SessionState
    live: bool

    @classmethod
    def from_core(cls, row: SessionRow, state: SessionState, live: bool) -> SessionOut:
        return cls(
            session_id=row.session_id,
            course=row.course,
            started_at=row.started_at,
            ended_at=row.ended_at,
            last_turn_at=row.last_turn_at,
            tutor_provider=row.tutor_provider,
            analyzer_provider=row.analyzer_provider,
            state=state,
            live=live,
        )
