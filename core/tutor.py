"""A tutoring session: compile each question, route it, keep the transcript in the vault.

A session on a course with pending challenges opens with them (BL-030): one Challenger probe per
concept, each answer graded alone before tutoring starts.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from core.analysis.analyzer import AnalysisError
from core.analysis.challenge import (
    Challenge,
    ChallengeRunner,
    Probe,
    estimate_task,
    format_estimate,
    parse_estimate,
)
from core.context.compiler import ContextCompiler, Turn, TutorSession, sources_unavailable
from core.ledger.ledger import utcnow
from core.memory.learner import LearnerMemory, SessionRow
from core.memory.vault import Vault
from core.personas import MissingAnchor, PersonaError, load
from core.providers.knowledge.base import GroundedAnswer, KnowledgeError
from core.providers.models.base import ModelError
from core.router.router import Router

log = logging.getLogger(__name__)

HELP = (
    "Commands: /ask <question> asks the course sources directly, /persona <name> switches"
    " persona, /rate 1-5 rates the last answer, /skip defers open challenges, /end closes the"
    " session, /help shows this."
)


class Tutor:
    def __init__(
        self,
        course: str,
        persona: str,
        compiler: ContextCompiler,
        router: Router,
        learner: LearnerMemory,
        vault: Vault,
        on_end: Callable[[Tutor], str | None] | None = None,
        challenges: ChallengeRunner | None = None,
    ) -> None:
        self.course = course
        self.persona = load(persona).name
        self._compiler = compiler
        self._router = router
        self._learner = learner
        self._vault = vault
        self._on_end = on_end
        self.row: SessionRow | None = None
        self.session: TutorSession | None = None
        self.providers_used: list[str] = []
        self.last_answer: tuple[str, str] | None = None  # (provider, task type), for /rate
        # Why the last line handled got no tutor answer (every provider failed, or the persona
        # had no anchor); None after any other line.
        self.last_error: ModelError | MissingAnchor | None = None
        self.ended = False
        self._challenges = challenges
        self._queue: list[Challenge] = []
        self.probe: Probe | None = None  # the Challenger question awaiting an answer

    @property
    def transcript_path(self) -> Path:
        assert self.row is not None
        return self._vault.session_transcript_path(self.row.session_id)

    def start(self) -> SessionRow:
        self.row = self._learner.start_session(self.course)
        self.session = TutorSession(self.row.session_id, self.course)
        path = self.transcript_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"---\nsession_id: {self.row.session_id}\ncourse: {self.course}\n"
            f"started_at: '{self.row.started_at}'\n---\n\n"
            f"# Tutor session {self.row.session_id} · {self.course}\n",
            encoding="utf-8",
        )
        if self._challenges is not None:
            self._queue = self._challenges.pending(self.course)
        return self.row

    def opening(self) -> str | None:
        """The first Challenger probe, when the course has pending challenges."""
        return self._next_probe()

    def handle(self, line: str) -> str | None:
        """One line of input: a command or a question. Returns what to show the learner."""
        self.last_error = None
        line = line.strip()
        if not line:
            return None
        if line == "/help":
            return HELP
        if line == "/end":
            return self.end()
        if line == "/skip":
            return self.skip()
        if line.startswith("/rate"):
            return self.rate(line.removeprefix("/rate").strip())
        if line.startswith("/persona"):
            return self.switch(line.removeprefix("/persona").strip())
        if line == "/ask" or line.startswith("/ask "):
            return self.ground(line.removeprefix("/ask").strip())
        if line.startswith("/"):
            return f"Unknown command {line.split()[0]}. {HELP}"
        if self.probe is not None:
            return self.answer_probe(line)
        return self.ask(line)

    def switch(self, name: str) -> str:
        try:
            persona = load(name)
        except PersonaError as exc:
            return str(exc)
        if persona.min_anchor_level is not None and not any(
            a["level"] >= persona.min_anchor_level for a in self._compiler.anchors(self.course)
        ):
            return (
                f"{name} needs a concept you've mastered at level {persona.min_anchor_level}+ "
                f"to build on; staying with {self.persona}."
            )
        self.persona = persona.name
        self._append(f"\n_Persona switched to {persona.name}._\n")
        return f"Persona: {persona.name}"

    def ground(self, question: str) -> str:
        """``/ask``: NotebookLM's grounded answer, in this session's conversation (P66), with
        its citations listed under it; when NotebookLM fails, a line saying so."""
        if not question:
            return "Usage: /ask <question>"
        try:
            answer = self.ground_answer(question)
        except KnowledgeError as exc:
            return sources_unavailable(exc)
        return self._compiler.flatten(answer, self.course)

    def ground_answer(self, question: str) -> GroundedAnswer:
        """``ground``'s answer with its citations as data (the web chat's chips), recorded in
        the transcript as ``ground``'s text. A NotebookLM failure is recorded, then raised."""
        assert self.session is not None, "call start() first"
        try:
            answer = self._compiler.ground_answer(question, self.course, self.session)
        except KnowledgeError as exc:
            log.warning("No grounded answer for %s: %s", self.course, exc)
            self._record_ask(question, sources_unavailable(exc))
            raise
        self._record_ask(question, self._compiler.flatten(answer, self.course))
        return answer

    def _record_ask(self, question: str, text: str) -> None:
        self._touch()
        quoted = "\n".join(f"> {line}" for line in text.splitlines())
        self._append(f"\n**Ask (NotebookLM):** {question}\n\n{quoted}\n")

    def ask(self, question: str) -> str:
        assert self.session is not None, "call start() first"
        self.last_error = None
        try:
            task = self._compiler.compile(question, self.course, self.persona, self.session)
            result = self._router.run(task)
        except (ModelError, MissingAnchor) as exc:
            log.warning("Tutor turn failed: %s", exc)
            self.last_error = exc
            return f"(no answer: {exc})"
        self.session.turns += [Turn("learner", question), Turn("tutor", result.text)]
        self.last_answer = (result.provider, task.task_type)
        self._touch()
        if result.provider not in self.providers_used:
            self.providers_used.append(result.provider)
        self._append(
            f"\n**Learner:** {question}\n\n"
            f"**Tutor ({self.persona} · {result.provider}):** {result.text}\n"
        )
        return result.text

    def rate(self, value: str) -> str:
        """``/rate 1-5``: the learner's rating of the last answer, a benchmark sample (BL-035)."""
        if self.last_answer is None:
            return "Nothing to rate yet."
        if value not in {"1", "2", "3", "4", "5"}:
            return "Usage: /rate 1-5"
        provider, task_type = self.last_answer
        self._router.rate(provider, task_type, int(value))
        self._append(f"\n_Rated {value}/5 ({provider})._\n")
        return f"Rated the last answer {value}/5."

    # -- challenges --------------------------------------------------------------------------

    def _next_probe(self) -> str | None:
        """Ask the next queued challenge (at most one per concept per session)."""
        assert self.session is not None, "call start() first"
        while self._queue and self._challenges is not None:
            challenge = self._queue.pop(0)
            try:
                probe = self._challenges.ask(challenge, self.session)
            except ModelError as exc:
                log.warning("Challenge %d not asked: %s", challenge.id, exc)
                continue  # stays pending for next session
            self.probe = probe
            self._append(
                f"\n**Challenge (challenger · {probe.provider or 'asked before'}) on "
                f"{probe.concept.name}:** {probe.question}\n"
            )
            return f"**Challenge · {probe.concept.name}**\n\n{probe.question}"
        return None

    def answer_probe(self, answer: str) -> str:
        assert self.probe is not None and self.row is not None and self._challenges is not None
        probe, self.probe = self.probe, None
        self._touch()
        self._append(f"\n**Learner (challenge answer):** {answer}\n")
        try:
            report = self._challenges.grade(probe, answer, self.row)
            note = f"Challenge graded by {report.provider}: {len(report.evidence_ids)} evidence."
            for change in report.applied:
                note += f" Upheld: {probe.concept.name} is now level {change.proposed}."
        except AnalysisError as exc:
            log.warning("Challenge %d not graded: %s", probe.challenge.id, exc)
            note = f"Challenge not graded ({exc}); it will be asked again next session."
        self._append(f"\n_{note}_\n")
        following = self._next_probe()
        return f"{note}\n\n{following}" if following else f"{note} Now, what shall we work on?"

    def skip(self) -> str:
        if self.probe is None and not self._queue:
            return "No open challenges."
        skipped = len(self._queue) + (self.probe is not None)
        self.probe, self._queue = None, []
        self._append(f"\n_{skipped} challenge(s) deferred._\n")
        return f"{skipped} challenge(s) deferred to a later session."

    def self_estimate(self) -> tuple[dict[str, int], str] | None:
        """The tutor's own one-line estimate of the concepts that came up, from the provider(s)
        that tutored. None when there was no tutoring or the call failed."""
        if not self.session or not self.session.turns or not self.providers_used:
            return None
        concepts = self._learner.concepts(self.course)
        if not concepts:
            return None
        others = set(self._router.providers) - set(self.providers_used)
        try:
            result = self._router.run(
                estimate_task(self.course, concepts, self.session.turns), exclude=others
            )
        except ModelError as exc:
            log.warning("No tutor estimate: %s", exc)
            return None
        estimate = parse_estimate(result.text, concepts)
        return estimate, format_estimate(estimate, concepts)

    def end(self) -> str:
        assert self.row is not None
        self.ended = True
        self.row.ended_at = utcnow()
        self.row.tutor_provider = ",".join(self.providers_used) or None
        self._learner.update_session(self.row)
        self._append(f"\n_Session ended {self.row.ended_at}._\n")
        note = self._on_end(self) if self._on_end else None
        return "Session ended." + (f" {note}" if note else "")

    def _touch(self) -> None:
        """A turn happened: the session isn't idle (BL-040)."""
        if self.row is not None:
            self._learner.touch_session(self.row)

    def _append(self, text: str) -> None:
        with self.transcript_path.open("a", encoding="utf-8") as f:
            f.write(text)
