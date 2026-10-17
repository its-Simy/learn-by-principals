"""Taking an exam: one question at a time, every answer timestamped and saved as it's given.

Running ``take`` again resumes an unfinished attempt; after a finished one it starts a new one.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.exams.paper import latest_attempt, load, mc_choice, save
from core.ledger.ledger import utcnow


def current_question(exam: dict[str, Any], attempt: dict[str, Any]) -> dict[str, Any] | None:
    """The first question ``attempt`` hasn't answered or skipped. A function of the file, so the
    attempt can be shown without an ``ExamTaker``, which opens one."""
    answers = attempt["answers"]
    return next((q for q in exam["questions"] if str(q["index"]) not in answers), None)


class ExamTaker:
    def __init__(self, path: Path, now: Callable[[], str] = utcnow) -> None:
        self.path = path
        self.exam = load(path)
        self._now = now
        attempt = latest_attempt(self.exam)
        self.resumed = attempt is not None and not attempt.get("finished_at")
        if not self.resumed:
            attempt = {
                "attempt": len(self.exam["attempts"]) + 1,
                "started_at": now(),
                "finished_at": None,
                "answers": {},
            }
            self.exam["attempts"].append(attempt)
            save(path, self.exam)
        assert attempt is not None
        self.attempt: dict[str, Any] = attempt

    @property
    def questions(self) -> list[dict[str, Any]]:
        return self.exam["questions"]

    def current(self) -> dict[str, Any] | None:
        return current_question(self.exam, self.attempt)

    def answer(self, reply: str) -> None:
        """Record ``reply`` for the current question. A multiple-choice reply must pick an
        option (by letter or text), otherwise ValueError and nothing is recorded."""
        question = self.current()
        if question is None:
            raise ValueError("every question is answered")
        reply = reply.strip()
        if not reply:
            raise ValueError("empty answer; type /skip to skip")
        value = reply
        if question["format"] == "multiple_choice":
            choice = mc_choice(question, reply)
            if choice is None:
                raise ValueError("pick one of the options by letter")
            value = choice
        self._record(question, {"answer": value, "raw": reply, "skipped": False})

    def skip(self) -> None:
        question = self.current()
        if question is not None:
            self._record(question, {"answer": None, "raw": None, "skipped": True})

    def finish(self) -> None:
        self.attempt["finished_at"] = self._now()
        save(self.path, self.exam)

    def _record(self, question: dict[str, Any], entry: dict[str, Any]) -> None:
        self.attempt["answers"][str(question["index"])] = {**entry, "answered_at": self._now()}
        save(self.path, self.exam)
