"""Persona skill files (``personas/*.md``): parse them and render one into a system prompt."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PERSONAS_DIR = Path(__file__).resolve().parents[1] / "personas"
SECTIONS = ("Goal", "Process", "Rules", "Output shape", "Known failure modes")

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_HEADING = re.compile(r"^## (.+)$", re.MULTILINE)


class PersonaError(Exception):
    pass


class MissingAnchor(PersonaError):
    """The persona needs an anchor concept the learner has mastered, and none was supplied."""


@dataclass(frozen=True)
class Anchor:
    concept: str
    level: int


@dataclass(frozen=True)
class Persona:
    name: str
    group: str
    task_types: tuple[str, ...]
    min_anchor_level: int | None
    sections: dict[str, str] = field(hash=False)

    @property
    def rules(self) -> list[str]:
        return [
            line[2:].strip()
            for line in self.sections["Rules"].splitlines()
            if line.startswith("- ")
        ]


def load(name: str, directory: Path = PERSONAS_DIR) -> Persona:
    path = directory / f"{name}.md"
    if not path.exists():
        raise PersonaError(f"No persona {name!r} in {directory}")
    match = _FRONT_MATTER.match(path.read_text(encoding="utf-8"))
    if not match:
        raise PersonaError(f"{path} has no front matter")
    meta: dict[str, Any] = yaml.safe_load(match.group(1)) or {}
    body = match.group(2)
    headings = [*_HEADING.finditer(body)]
    sections = {
        h.group(1).strip(): body[h.end() : nxt.start() if nxt else len(body)].strip()
        for h, nxt in zip(headings, [*headings[1:], None], strict=True)
    }
    missing = [s for s in SECTIONS if s not in sections]
    if missing:
        raise PersonaError(f"{path} is missing sections: {', '.join(missing)}")
    for key in ("name", "group", "task_types"):
        if key not in meta:
            raise PersonaError(f"{path} front matter has no {key!r}")
    if meta["name"] != name:
        raise PersonaError(f"{path} says name {meta['name']!r}")
    return Persona(
        name=meta["name"],
        group=meta["group"],
        task_types=tuple(meta["task_types"]),
        min_anchor_level=meta.get("min_anchor_level"),
        sections=sections,
    )


def list_personas(directory: Path = PERSONAS_DIR) -> list[str]:
    return sorted(p.stem for p in directory.glob("*.md"))


list = list_personas  # noqa: A001  (the ticket's name for it)


def _anchors(context: dict[str, Any]) -> list[Anchor]:
    anchors = []
    for a in context.get("anchors") or []:
        anchors.append(a if isinstance(a, Anchor) else Anchor(a["concept"], int(a["level"])))
    return anchors


def render(persona: Persona, context: dict[str, Any] | None = None) -> str:
    """The persona as a system prompt. ``context`` may carry ``course`` and ``anchors``
    (``[{"concept", "level"}]``); personas with ``min_anchor_level`` refuse to render without one.
    """
    context = context or {}
    anchors = _anchors(context)
    if persona.min_anchor_level is not None:
        anchors = [a for a in anchors if a.level >= persona.min_anchor_level]
        if not anchors:
            raise MissingAnchor(
                f"{persona.name} needs an anchor concept at mastery level "
                f"{persona.min_anchor_level} or higher"
            )
    title = persona.name.capitalize()
    parts = [f"You are the {title} persona, a {persona.group} strategy in BrightLearn."]
    if context.get("course"):
        parts[0] += f" The course is {context['course']}."
    for section in SECTIONS:
        parts.append(f"## {section}\n{persona.sections[section]}")
    if anchors:
        listed = "\n".join(f"- {a.concept} (level {a.level})" for a in anchors)
        parts.append(f"## Anchor concepts the learner has mastered\n{listed}")
    return "\n\n".join(parts)
