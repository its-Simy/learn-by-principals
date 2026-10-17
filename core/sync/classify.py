"""Bucket for a course file, from keywords in its title and filename.

Rules are checked in order; the first match wins. Source-code extensions are checked after the
syllabus/exam/lab/assignment keywords (starter code stays with its assignment) and before the
lecture/reading keywords (lecture demo code goes to ``code``). When no rule matches, the title is
ambiguous: a ``fallback`` (``ModelClassifier``: the local Ollama model, only when it's AVAILABLE)
may name the bucket instead of ``other`` (BL-036).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import PurePath

from core.providers.models.base import ModelError, TaskPackage
from core.providers.state import ProviderState
from core.router.router import Router

log = logging.getLogger(__name__)

BUCKETS = ("syllabus", "lectures", "assignments", "labs", "readings", "exams", "code", "other")

CODE_EXTENSIONS = frozenset(
    {
        ".c",
        ".h",
        ".s",
        ".asm",
        ".py",
        ".java",
        ".cpp",
        ".hpp",
        ".js",
        ".ts",
        ".ipynb",
        ".sh",
        ".mk",
        ".rs",
        ".go",
    }
)

_RULES: list[tuple[str, re.Pattern[str] | None]] = [
    ("syllabus", re.compile(r"\bsyllabus\b")),
    ("exams", re.compile(r"\b(exams?|midterms?|quiz(zes)?|study guides?|practice tests?)\b")),
    ("labs", re.compile(r"\b(labs?|recitations?)\s*\d*\b")),
    (
        "assignments",
        re.compile(r"\b(assignments?|homeworks?|hw\s*\d*|problem sets?|psets?|projects?)\b"),
    ),
    ("code", None),
    ("lectures", re.compile(r"\b(lectures?|lec\s*\d*|slides?|notes)\b")),
    ("readings", re.compile(r"\b(readings?|chapters?|ch\s*\d+|textbooks?|articles?|papers?)\b")),
]


def _normalise(text: str) -> str:
    # Split camelCase and treat _ - . as word breaks so "Lab_3" and "hw2" match.
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", text)
    return re.sub(r"[_\-.]+", " ", text).lower()


Fallback = Callable[[str, str | None], str | None]


def classify(title: str, filename: str | None = None, fallback: Fallback | None = None) -> str:
    haystack = _normalise(" ".join([title, filename or ""]))
    is_code = bool(filename) and PurePath(filename).suffix.lower() in CODE_EXTENSIONS
    for bucket, pattern in _RULES:
        if pattern is None:
            if is_code:
                return bucket
        elif pattern.search(haystack):
            return bucket
    if fallback is not None:
        guess = fallback(title, filename)
        if guess in BUCKETS:
            return guess
    return "other"


CLASSIFY_SYSTEM = (
    "You sort files from a university course site into one bucket: "
    + ", ".join(BUCKETS)
    + ". Reply with the bucket name only."
)


class ModelClassifier:
    """The ``classify`` task on the local model, asked only when that provider is AVAILABLE."""

    def __init__(self, router: Router, provider: str = "ollama") -> None:
        self._router = router
        self._provider = provider

    def __call__(self, title: str, filename: str | None) -> str | None:
        if self._provider not in self._router.providers:
            return None
        if self._router.state(self._provider) is not ProviderState.AVAILABLE:
            return None
        user = f"Title: {title}\nFilename: {filename or '(none)'}"
        others = set(self._router.providers) - {self._provider}
        task = TaskPackage("classify", None, CLASSIFY_SYSTEM, user, 10)
        try:
            text = self._router.run(task, exclude=others).text
        except ModelError as exc:
            log.warning("Model classification failed for %r: %s", title, exc)
            return None
        words = re.findall(r"[a-z]+", text.lower())
        return next((w for w in words if w in BUCKETS), None)
