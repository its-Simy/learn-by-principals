"""A tutoring session: compile each question, route it, keep the transcript in the vault."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from core.context.compiler import ContextCompiler, Turn, TutorSession
from core.ledger.ledger import utcnow
from core.memory.learner import LearnerMemory, SessionRow
from core.memory.vault import Vault
from core.personas import MissingAnchor, PersonaError, load
from core.providers.models.base import ModelError
from core.router.router import Router

log = logging.getLogger(__name__)

HELP = "Commands: /persona <name> switches persona, /end closes the session, /help shows this."


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
        self.ended = False

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
            f"# Tutor session {self.row.session_id} · {self.course}\n"
        )
        return self.row

    def handle(self, line: str) -> str | None:
        """One line of input: a command or a question. Returns what to show the learner."""
        line = line.strip()
        if not line:
            return None
        if line == "/help":
            return HELP
        if line == "/end":
            return self.end()
        if line.startswith("/persona"):
            return self.switch(line.removeprefix("/persona").strip())
        if line.startswith("/"):
            return f"Unknown command {line.split()[0]}. {HELP}"
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

    def ask(self, question: str) -> str:
        assert self.session is not None, "call start() first"
        try:
            task = self._compiler.compile(question, self.course, self.persona, self.session)
            result = self._router.run(task)
        except (ModelError, MissingAnchor) as exc:
            log.warning("Tutor turn failed: %s", exc)
            return f"(no answer: {exc})"
        self.session.turns += [Turn("learner", question), Turn("tutor", result.text)]
        if result.provider not in self.providers_used:
            self.providers_used.append(result.provider)
        self._append(
            f"\n**Learner:** {question}\n\n"
            f"**Tutor ({self.persona} · {result.provider}):** {result.text}\n"
        )
        return result.text

    def end(self) -> str:
        assert self.row is not None
        self.ended = True
        self.row.ended_at = utcnow()
        self.row.tutor_provider = ",".join(self.providers_used) or None
        self._learner.update_session(self.row)
        self._append(f"\n_Session ended {self.row.ended_at}._\n")
        note = self._on_end(self) if self._on_end else None
        return "Session ended." + (f" {note}" if note else "")

    def _append(self, text: str) -> None:
        with self.transcript_path.open("a") as f:
            f.write(text)
