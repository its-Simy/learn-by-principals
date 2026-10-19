"""Fake Questioner and Critic models for exam tests: they answer whatever the task lists."""

from __future__ import annotations

import json
import re

from core.providers.models.base import ModelResult, UsageHint
from tests.fakes.fake_models import FakeModel

SLOT = re.compile(r"^\d+\. (multiple_choice|short_answer|coding), (easy|medium|hard)$", re.M)
CONCEPT_ID = re.compile(r"\(concept_id ([^\s)]+)\)")
GRADE_BLOCK = re.compile(
    r"### Question (\d+) .*?Learner's answer:\n(.*?)(?=\n### Question|\n\n## Output)", re.S
)


def question(concept_id: str, fmt: str, difficulty: str, n: int = 0) -> dict:
    q = {
        "stem": f"Q{n} about {concept_id} ({fmt}, {difficulty})?",
        "answer": "B" if fmt == "multiple_choice" else "the reference answer",
        "rubric": "Mentions the key idea.",
        "difficulty": difficulty,
        "concept_id": concept_id,
        "format": fmt,
    }
    if fmt == "multiple_choice":
        q["options"] = ["A", "B", "C", "D"]
    return q


class FakeQuestioner(FakeModel):
    """Writes valid questions for the slots a question_gen task lists; ``spoil`` may corrupt."""

    def __init__(self, name: str, spoil=None, reply: str = "ok") -> None:
        super().__init__(name, reply)
        self.spoil = spoil or (lambda task, items: items)

    def run(self, task):
        if task.task_type != "question_gen":
            return super().run(task)
        self.tasks.append(task)
        concept_id = CONCEPT_ID.search(task.user).group(1)
        items = [question(concept_id, f, d, len(self.tasks)) for f, d in SLOT.findall(task.user)]
        text = "```json\n" + json.dumps(self.spoil(task, items)) + "\n```"
        return ModelResult(text, self.name, None, 5, UsageHint())


class FakeCritic(FakeModel):
    """Critique: flags nothing. Grading: an answer is correct when it contains "correct"."""

    def run(self, task):
        if task.task_type == "critique":
            self.tasks.append(task)
            return ModelResult("[]", self.name, None, 5, UsageHint())
        if task.task_type == "grade":
            self.tasks.append(task)
            if self.limited:
                return super().run(task)
            grades = [
                {"index": int(i), "correct": "correct" in a.lower(), "feedback": "ok"}
                for i, a in GRADE_BLOCK.findall(task.user)
            ]
            return ModelResult(json.dumps(grades), self.name, None, 5, UsageHint())
        return super().run(task)
