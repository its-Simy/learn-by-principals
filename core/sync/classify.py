"""Drive bucket for a resource, from keywords in its module path, title and filename.

Rules are checked in order; the first match wins. Source-code extensions are checked after the
syllabus/exam/lab/assignment keywords (starter code stays with its assignment) and before the
lecture/reading keywords (lecture demo code goes to ``code``). Deterministic on purpose: a
model-backed ``classify`` task can replace this once the router exists.
"""

from __future__ import annotations

import re
from pathlib import PurePath

from core.providers.lms.base import Resource

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


def classify(resource: Resource, filename: str | None = None) -> str:
    haystack = _normalise(" ".join([resource.module_path, resource.title, filename or ""]))
    is_code = bool(filename) and PurePath(filename).suffix.lower() in CODE_EXTENSIONS
    for bucket, pattern in _RULES:
        if pattern is None:
            if is_code:
                return bucket
        elif pattern.search(haystack):
            return bucket
    return "other"
