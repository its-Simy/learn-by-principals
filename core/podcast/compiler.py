"""Adaptive podcast context (BL-034): learner state -> a short Markdown brief for NotebookLM's
Audio Overview, so each episode differs because the learner model changed.

The brief says what to skip (level 4+ with retention 0.7+), what to dwell on (the weakest
concepts, within the exam's coverage when there is one), which misconceptions to confront (from
misconception evidence and the vault's concept notes), how the learner likes to be taught
(``vault/learner/profile.md``), how the exam frames it, and how to end. It stays under
``WORD_CAP`` words by trimming its lists.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field

from core.exams.coverage import PlanError, matches, plan
from core.exams.spec import ExamSpec
from core.memory.learner import Concept, LearnerMemory, Mastery
from core.memory.vault import Vault

SKIP_LEVEL = 4
SKIP_RETENTION = 0.7
WORD_CAP = 400
FOCUS_MAX, FOCUS_MIN = 5, 2
MISCONCEPTIONS_MAX = 3
SKIP_MAX = 8
PREFERENCE_WORDS = 60
DEFAULT_PREFERENCE = (
    "No stated preference yet: explain plainly, one concrete worked example per idea, and "
    "define every term before using it."
)
_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


@dataclass
class PodcastContext:
    course: str
    exam: str | None
    skip: list[Concept] = field(default_factory=list)
    focus: list[tuple[Concept, Mastery | None]] = field(default_factory=list)
    misconceptions: list[tuple[str, str]] = field(default_factory=list)  # (concept name, text)
    preference: str = DEFAULT_PREFERENCE
    framing: str = ""
    text: str = ""

    @property
    def concept_ids(self) -> list[str]:
        """The concepts this episode targets (for the ``podcasts`` row)."""
        return [c.concept_id for c, _ in self.focus]


def words(text: str) -> int:
    return len(text.split())


def compile_podcast_context(
    course: str, exam_spec: ExamSpec | None, learner: LearnerMemory, vault: Vault | None = None
) -> str:
    return build_podcast_context(course, exam_spec, learner, vault).text


def build_podcast_context(
    course: str, exam_spec: ExamSpec | None, learner: LearnerMemory, vault: Vault | None = None
) -> PodcastContext:
    concepts = learner.concepts(course)
    mastery = {c.concept_id: m for c in concepts if (m := learner.get_mastery(c.concept_id))}
    scope = _scope(exam_spec, concepts, mastery)

    def skippable(c: Concept) -> bool:
        m = mastery.get(c.concept_id)
        return bool(
            m and m.level >= SKIP_LEVEL and (m.retention_confidence or 0.0) >= SKIP_RETENTION
        )

    context = PodcastContext(course, exam_spec.exam if exam_spec else None)
    context.skip = [c for c in scope if skippable(c)]
    context.focus = [(c, mastery.get(c.concept_id)) for c in scope if not skippable(c)][:FOCUS_MAX]
    context.misconceptions = _misconceptions([c for c, _ in context.focus], learner, vault)[
        :MISCONCEPTIONS_MAX
    ]
    context.preference = _preference(vault)
    context.framing = _framing(exam_spec)
    context.text = _fit(context)
    return context


def _scope(
    spec: ExamSpec | None, concepts: list[Concept], mastery: dict[str, Mastery]
) -> list[Concept]:
    """Candidate concepts, weakest first: the exam's coverage plan (weighted as ``weakness``)
    when there's an exam, otherwise the whole course in ``weakest()`` order."""
    if spec is not None:
        try:
            rows = plan(dataclasses.replace(spec, mode="weakness"), concepts, mastery).rows
            chosen = [r.concept for r in rows]
            # Concepts too light to get a question still belong to the exam's scope.
            rest = [c for c in concepts if c not in chosen and _in_scope(spec, c)]
            return chosen + sorted(rest, key=lambda c: _weakness(c, mastery))
        except PlanError:
            pass
    return sorted(concepts, key=lambda c: _weakness(c, mastery))


def _in_scope(spec: ExamSpec, c: Concept) -> bool:
    if any(matches(c, n) for n in spec.exclude):
        return False
    return not spec.weeks or c.week in spec.weeks or any(matches(c, n) for n in spec.include)


def _weakness(c: Concept, mastery: dict[str, Mastery]) -> tuple:
    m = mastery.get(c.concept_id)
    if m is None:
        return (0, 0.0, 0.0, c.name.lower())
    return (m.level, m.retention_confidence or 0.0, m.confidence, c.name.lower())


def _misconceptions(
    focus: list[Concept], learner: LearnerMemory, vault: Vault | None
) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for concept in focus:
        texts = [
            e.excerpt_ref
            for e in reversed(learner.evidence(concept.concept_id))
            if e.type == "misconception" and e.excerpt_ref
        ]
        if vault is not None:
            texts += _note_misconceptions(vault, concept)
        for text in texts:
            text = " ".join(text.split())
            if text.lower() not in seen:
                seen.add(text.lower())
                found.append((concept.name, text))
    return found


def _note_misconceptions(vault: Vault, concept: Concept) -> list[str]:
    """Bullets under ``## Misconceptions`` in the concept's vault note."""
    path = vault.concept_path(concept)
    if not path.exists():
        return []
    body = _FRONT_MATTER.sub("", path.read_text(encoding="utf-8"))
    match = re.search(r"^## Misconceptions\n(.*?)(?=^## |\Z)", body, re.MULTILINE | re.DOTALL)
    if not match:
        return []
    bullets = [line[2:].strip() for line in match.group(1).splitlines() if line.startswith("- ")]
    return [b for b in bullets if b and b != "none recorded"]


def _preference(vault: Vault | None) -> str:
    if vault is None:
        return DEFAULT_PREFERENCE
    path = vault.root / "learner" / "profile.md"
    if not path.exists():
        return DEFAULT_PREFERENCE
    body = _FRONT_MATTER.sub("", path.read_text(encoding="utf-8"))
    lines = [ln.strip().lstrip("-*").strip() for ln in body.splitlines()]
    text = "; ".join(ln for ln in lines if ln and not ln.startswith("#"))
    return _clip(text, PREFERENCE_WORDS) or DEFAULT_PREFERENCE


def _framing(spec: ExamSpec | None) -> str:
    if spec is None:
        return "No exam is scheduled: aim for durable understanding, not test tricks."
    formats = ", ".join(f"{n} {f.replace('_', ' ')}" for f, n in spec.formats.items())
    weeks = f"weeks {', '.join(map(str, spec.weeks))}" if spec.weeks else "the course so far"
    return (
        f"This episode prepares for {spec.exam}, which covers {weeks} ({formats} questions). "
        "Point out where each idea is likely to be tested and how a question on it might be "
        "phrased."
    )


def _focus_line(concept: Concept, m: Mastery | None) -> str:
    level = m.level if m else 0
    if level <= 1:
        how = "introduce it from scratch with one concrete example"
    elif level == 2:
        how = "they can explain it; walk through applying it to a standard problem"
    else:
        how = "they can apply it; stretch them with an unfamiliar variant"
    retention = f", retention {m.retention_confidence:.1f}" if m and m.retention_confidence else ""
    return f"- **{concept.name}** (level {level}/5{retention}): {how}."


def _render(ctx: PodcastContext, n_skip: int, n_focus: int, n_misc: int, pref_words: int) -> str:
    title = f"{ctx.course} · {ctx.exam}" if ctx.exam else ctx.course
    lines = [
        f"# Audio Overview brief: {title}",
        "",
        "This episode is for one student. Shape it around what they have and haven't shown yet.",
        "",
        "## Teaching preference",
        _clip(ctx.preference, pref_words),
        "",
        "## Skip: already mastered",
    ]
    if ctx.skip and n_skip:
        names = ", ".join(c.name for c in ctx.skip[:n_skip])
        more = f" and {len(ctx.skip) - n_skip} more" if len(ctx.skip) > n_skip else ""
        lines.append(f"Mention only in passing: {names}{more}.")
    else:
        lines.append("Nothing is mastered yet; assume no prior knowledge beyond the basics.")
    lines += ["", "## Dwell on"]
    focus = ctx.focus[:n_focus]
    lines += [_focus_line(c, m) for c, m in focus] or ["- The course's core ideas, in order."]
    if ctx.misconceptions and n_misc:
        lines += [
            "",
            "## Misconceptions to confront",
            "Name each one, show why it's tempting, then correct it with an example:",
        ]
        lines += [f'- "{text}" ({name})' for name, text in ctx.misconceptions[:n_misc]]
    lines += ["", "## Exam framing", ctx.framing, "", "## How to end"]
    targets = [c.name for c, _ in focus[:2]]
    if targets:
        count = (
            "two short thought experiments" if len(targets) == 2 else "a short thought experiment"
        )
        lines.append(
            f"Close with {count} on {' and '.join(targets)}: pose a what-if, pause so the listener "
            "can predict the answer, then reason it through."
        )
    else:
        lines.append("Close with one short thought experiment the listener can reason through.")
    return "\n".join(lines) + "\n"


def _fit(ctx: PodcastContext) -> str:
    """The fullest rendering under ``WORD_CAP``, trimming lists before the preference."""
    n_skip, n_focus, n_misc, pref = SKIP_MAX, FOCUS_MAX, MISCONCEPTIONS_MAX, PREFERENCE_WORDS
    steps = [
        ("skip", 3),
        ("misc", 1),
        ("focus", FOCUS_MIN + 1),
        ("pref", 25),
        ("skip", 0),
        ("focus", FOCUS_MIN),
        ("misc", 0),
        ("pref", 10),
    ]
    text = _render(ctx, n_skip, n_focus, n_misc, pref)
    for knob, floor in steps:
        while words(text) > WORD_CAP:
            if knob == "skip" and n_skip > floor:
                n_skip -= 1
            elif knob == "misc" and n_misc > floor:
                n_misc -= 1
            elif knob == "focus" and n_focus > floor:
                n_focus -= 1
            elif knob == "pref" and pref > floor:
                pref = max(floor, pref - 5)
            else:
                break
            text = _render(ctx, n_skip, n_focus, n_misc, pref)
    if words(text) > WORD_CAP:  # very long names or excerpts: keep whole lines up to the cap
        kept, total = [], 0
        for line in text.splitlines():
            if total + words(line) > WORD_CAP:
                break
            kept.append(line)
            total += words(line)
        text = "\n".join(kept) + "\n"
    ctx.focus = ctx.focus[:n_focus]
    return text


def _clip(text: str, n: int) -> str:
    parts = text.split()
    return " ".join(parts[:n]) + ("…" if len(parts) > n else "")
