"""The web API on fakes, for developing the UI without NotebookLM or the model CLIs.

    .venv/bin/python scripts/dev_server.py --home /tmp/brightlearn-dev [--port 8765] [--delay 1]

Serves ``create_app`` with the test fakes behind both workers, the way ``tests/conftest.py``'s
``api`` fixture does, against a scratch home: ``--home`` holds the database, the course files,
the vault and the temp dir, and nothing under ``~/.brightlearn`` is read or written. The first
start seeds CSE220 with three linked files and five concepts with mastery, so every pane has data;
later starts keep what the home holds. One Challenger probe (on Pointers) is queued for the first
session, and the fake Analyzer proposes a two-level jump at every session's end, so each ended
session queues another. Point Vite at it with ``VITE_API_PORT`` (web/README.md).

NotebookLM is an in-memory fake: it forgets its sources on exit, so each start re-adopts every
linked row from the manifest. ``--delay`` makes each fake call take that many seconds, so the
UI's waits (pending rows, elapsed times) can be seen; a file whose name contains "fail" is
refused by the fake, to show a link job's failure, and a tutor question that says "rate limit"
gets a usage limit from both fake models, to show a turn's error and its reset time.
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Outside pytest, the repo root isn't on sys.path (pyproject's pythonpath is pytest's), and the
# fakes live in tests/.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.app import create_app  # noqa: E402
from api.engine import Engine, Resources  # noqa: E402
from core.analysis.analyzer import learner_words  # noqa: E402
from core.analysis.challenge import ChallengeStore  # noqa: E402
from core.config import Config, ensure_home, load_config  # noqa: E402
from core.ledger.ledger import Ledger, ModelRun  # noqa: E402
from core.memory.db import Courses, Manifest, ResourceRow, connect  # noqa: E402
from core.memory.learner import Concept, LearnerMemory  # noqa: E402
from core.memory.seeding import concept_id  # noqa: E402
from core.providers.knowledge.base import (  # noqa: E402
    Citation,
    Conversation,
    GroundedAnswer,
    KnowledgeError,
    ProviderState,
    SourceMeta,
    notebook_title,
)
from core.providers.models.base import (  # noqa: E402
    ModelRateLimited,
    ModelResult,
    TaskPackage,
    UsageHint,
)
from core.providers.storage.local import LocalStorageBackend  # noqa: E402
from core.router.benchmarks import Benchmarks  # noqa: E402
from core.router.health import HealthStore  # noqa: E402
from core.sync.importer import Importer  # noqa: E402
from core.sync.link import LinkStep  # noqa: E402
from tests.fakes.fake_exam import FakeCritic, FakeQuestioner  # noqa: E402
from tests.fakes.fake_knowledge import FakeKnowledge, FakeSource  # noqa: E402

log = logging.getLogger("dev_server")

COURSE = "CSE220"
COURSE_NAME = "Systems Fundamentals I"

# (bucket, filename, text): small files, so the fake's citations quote real course text.
FILES = (
    (
        "syllabus",
        "CSE220 Syllabus.md",
        "# CSE220 Systems Fundamentals I\n\n"
        "Week 1: data representation, two's complement. Week 2: bitwise operators.\n"
        "Week 3: pointers and arrays. Week 4: dynamic memory allocation. Week 5: recursion.\n"
        "Midterm 1 covers weeks 1 to 3.\n",
    ),
    (
        "lectures",
        "Lecture 3 - Pointers.md",
        "# Lecture 3: Pointers\n\n"
        "A pointer holds the address of another object. `&x` takes an address and `*p` "
        "dereferences it. Pointer arithmetic moves in units of the pointed-to type.\n",
    ),
    (
        "assignments",
        "HW1 Bit Manipulation.txt",
        "HW1: Bit manipulation\n\n"
        "1. Write isPowerOfTwo(x) using only bitwise operators.\n"
        "2. Explain why x & (x - 1) clears the lowest set bit.\n",
    ),
)

# (name, module, week, level): levels spread over 0-5 so the mastery views have something to rank.
CONCEPTS = (
    ("Data representation", "Bits", 1, 4),
    ("Bitwise operators", "Bits", 2, 1),
    ("Pointers", "Memory", 3, 3),
    ("Dynamic memory allocation", "Memory", 4, 0),
    ("Recursion", "Control flow", 5, 2),
)

# What a seed job's NotebookLM query gets back: the JSON array core.memory.seeding parses.
SEED_ANSWER = """```json
[
 {"name": "Data representation", "module": "Bits", "week": 1, "prerequisites": [],
  "exam_tags": ["midterm-1"]},
 {"name": "Bitwise operators", "module": "Bits", "week": 2,
  "prerequisites": ["Data representation"], "exam_tags": ["midterm-1"]},
 {"name": "Pointers", "module": "Memory", "week": 3, "prerequisites": [],
  "exam_tags": ["midterm-1"]},
 {"name": "Dynamic memory allocation", "module": "Memory", "week": 4,
  "prerequisites": ["Pointers"], "exam_tags": ["final"]},
 {"name": "Recursion", "module": "Control flow", "week": 5, "prerequisites": [],
  "exam_tags": ["final"]},
 {"name": "Stack frames", "module": "Control flow", "week": 5, "prerequisites": ["Recursion"],
  "exam_tags": ["final"]}
]
```"""

SOURCE_ANSWER = """A **pointer** stores the address of another object rather than a value [1].

- `&x` gives the address of `x`; `*p` reads or writes what `p` points at [1].
- Pointer arithmetic moves in units of the pointed-to type, so `p + 1` on an `int *` \
advances by `sizeof(int)` bytes [2].

```c
int x = 7;
int *p = &x;
*p = 8;   /* x is now 8 */
```"""

TUTOR_ANSWER = """Think of memory as a long street of numbered houses. A **pointer** is a slip \
of paper with a house number on it, not the house itself [1].

1. `&x` asks "which house is `x` in?" and gives you the number.
2. `*p` walks to the house written on `p` and looks inside [1].
3. `p + 1` moves to the next house of the same size, which is why the type matters [2].

| Expression | Means |
| --- | --- |
| `p` | the address |
| `*p` | the value at that address |

Try this: if `int *p` holds `1000` and an `int` is 4 bytes, what does `p + 2` hold?"""

# The Challenger task names its concept as "## Concept\nName (recorded mastery: ...)".
PROBE_CONCEPT = re.compile(r"^## Concept\n(.+?) \(recorded", re.M)

# FakeQuestioner's slot lines: a question_gen task that lists slots is exam generation.
SLOT = re.compile(r"^\d+\. (multiple_choice|short_answer|coding), (easy|medium|hard)$", re.M)

# A tutoring question saying "rate limit" is refused by both models with a limit that resets in
# RATE_LIMIT_FOR, so the router skips them both until then, as it would a real limit.
RATE_LIMIT = re.compile(r"\brate limit\b", re.I)
RATE_LIMIT_FOR = timedelta(seconds=20)
TUTORING = frozenset({"explain", "analogy", "exemplify"})


class DevKnowledge(FakeKnowledge):
    """FakeKnowledge with Markdown answers citing up to two sources, the seed JSON for a seed
    query, a delay per call, ids that never repeat across restarts, and a refusal to link any
    file whose name contains "fail".

    Both workers share this one instance (as the ``api`` fixture shares its fake), so every call
    that reads or writes its dicts holds ``_lock``; the delays are spent outside it.
    """

    def __init__(self, out_dir: Path, delay: float) -> None:
        super().__init__(out_dir=out_dir, answer_text=SOURCE_ANSWER)
        self.delay = delay
        self._lock = threading.RLock()

    def adopt(self, rows: list[ResourceRow]) -> None:
        """Take back the linked rows of an earlier run: this fake forgets them on exit."""
        numbers = [0]
        with self._lock:
            for row in rows:
                if not (row.notebook_source_id and row.notebook_id and row.local_path):
                    continue
                path = Path(row.local_path)
                text = path.read_text(errors="replace") if path.exists() else ""
                self.sources[row.notebook_source_id] = FakeSource(
                    row.notebook_source_id, row.notebook_id, path, text
                )
                self.notebooks[notebook_title(row.course)] = row.notebook_id
                for value in (row.notebook_source_id, row.notebook_id):
                    numbers += [int(n) for n in re.findall(r"\d+", value)]
            self._ids = itertools.count(max(numbers) + 1)

    def ensure_notebook(self, course: str) -> str:
        with self._lock:
            return super().ensure_notebook(course)

    def add_file(self, notebook_id: str, path: Path) -> str:
        time.sleep(self.delay)
        if "fail" in path.name.lower():  # so the UI's failed-link state can be seen
            raise KnowledgeError(f"dev server refuses {path.name}: its name contains 'fail'")
        with self._lock:
            return super().add_file(notebook_id, path)

    def remove_source(self, source_id: str) -> None:
        with self._lock:
            super().remove_source(source_id)

    def list_sources(self, notebook_id: str) -> list[SourceMeta]:
        with self._lock:
            return super().list_sources(notebook_id)

    def source_fulltext(self, source_id: str) -> str:
        with self._lock:
            return super().source_fulltext(source_id)

    def query(
        self,
        notebook_id: str,
        question: str,
        source_ids: list[str] | None = None,
        conversation: Conversation | None = None,
    ) -> GroundedAnswer:
        """FakeKnowledge's conversation rule, but the answer and citations are built per call."""
        time.sleep(self.delay)
        with self._lock:
            self.queries.append((notebook_id, question, source_ids))
            if conversation is None or conversation.conversation_id is None:
                conversation_id = f"conv{next(self._ids)}"  # a fresh conversation
                if conversation is not None:
                    conversation.conversation_id = conversation_id
            else:
                conversation_id = conversation.conversation_id
            self.conversations.append(conversation_id)
            pool = [
                s
                for s in self.sources.values()
                if s.notebook_id == notebook_id
                and (source_ids is None or s.source_id in source_ids)
            ]
        text = SEED_ANSWER if "List the concepts" in question else SOURCE_ANSWER
        citations = [Citation(s.source_id, s.text[:160]) for s in pool[:2]]
        return GroundedAnswer(text, citations, conversation_id)

    def generate_quiz(self, notebook_id: str, spec: dict[str, Any] | None = None) -> dict:
        with self._lock:
            return super().generate_quiz(notebook_id, spec)

    def generate_audio(
        self, notebook_id: str, instructions_md: str, format: str, length: str
    ) -> Path:
        time.sleep(self.delay * 3)
        with self._lock:
            return super().generate_audio(notebook_id, instructions_md, format, length)

    def generate(self, notebook_id: str, kind: str, options: dict[str, Any]) -> Path:
        with self._lock:
            return super().generate(notebook_id, kind, options)


# The Analyzer's task lists "- Name: level n" per concept; core.analysis.analyzer formats it.
CONCEPT_LEVEL = re.compile(r"^- (.+): level (\d)$", re.M)
# A Challenger probe's answer is "**Learner:** ..." too, so one rule finds both.
LEARNER_TURN = re.compile(r"\*\*Learner:\*\*\s*(.+)")


def analyzer_finding(user: str) -> str:
    """Evidence on the weakest listed concept, quoting the learner's first turn, with a jump of
    two levels: more than the one step the Analyzer applies, so the session ends with a
    Challenger probe queued for the next (BL-030). A probe's answer is graded the same way and,
    proposing the challenged level or more, is upheld."""
    concepts = sorted(
        ((int(level), name) for name, level in CONCEPT_LEVEL.findall(user)), key=lambda c: c[0]
    )
    turn = LEARNER_TURN.search(user)
    if not concepts or turn is None or not learner_words(user):
        return "[]"
    level, name = concepts[0]
    finding = {
        "concept": name,
        "evidence_type": "explained",
        "strength": "moderate",
        "excerpt": turn.group(1).strip()[:200],
        "proposed_level": min(5, level + 2),
    }
    return "```json\n" + json.dumps([finding]) + "\n```"


class DevModel(FakeCritic):
    """One fake model for every task a route can send: a Markdown tutor answer, a Challenger
    probe, exam questions (FakeQuestioner), critique and grading (FakeCritic), and an Analyzer
    finding that queues the next probe (``analyzer_finding``)."""

    def __init__(self, name: str, delay: float) -> None:
        super().__init__(name, reply=TUTOR_ANSWER)
        self.delay = delay
        self._questioner = FakeQuestioner(name)

    def run(self, task: TaskPackage) -> ModelResult:
        time.sleep(self.delay)
        if task.task_type == "question_gen" and SLOT.search(task.user):
            return self._questioner.run(task)
        if task.task_type == "question_gen":  # the Challenger's probe
            found = PROBE_CONCEPT.search(task.user)
            concept = found.group(1) if found else "this concept"
            probe = f"Without notes: what is the key idea of **{concept}**, and where does it fail?"
            return self._text(task, probe)
        if task.task_type == "analyze_transcript":
            return self._text(task, analyzer_finding(task.user))
        if task.task_type == "tutor_estimate":
            return self._text(task, "")
        if task.task_type in TUTORING and RATE_LIMIT.search(task.user):
            resets = (datetime.now(UTC) + RATE_LIMIT_FOR).isoformat(timespec="seconds")
            message = f"{self.name} usage limit reached"
            raise ModelRateLimited(message, UsageHint(limit_message=message, resets_at=resets))
        return super().run(task)

    def _text(self, task: TaskPackage, text: str) -> ModelResult:
        self.tasks.append(task)
        return ModelResult(text, self.name, f"{self.name}-dev", 5, UsageHint(10, 2))


def scratch_config(home: Path) -> Config:
    """Everything under ``home``; the environment says so too, for any code that loads config
    itself (doctor reads the same paths)."""
    os.environ["BRIGHTLEARN_HOME"] = str(home)
    os.environ["BRIGHTLEARN_VAULT"] = str(home / "vault")
    os.environ["BRIGHTLEARN_TMP_DIR"] = str(home / "tmp")
    for name in ("BRIGHTLEARN_STORAGE_ROOT", "BRIGHTLEARN_DB"):
        os.environ.pop(name, None)
    return load_config()


def seed(config: Config, conn: sqlite3.Connection, knowledge: DevKnowledge) -> None:
    """CSE220 with three linked files, five concepts with mastery, one pending Challenger probe,
    healthy providers and a few ledger rows, so the dashboard isn't empty on first load."""
    Courses(conn).add(COURSE, COURSE_NAME, config.term)
    importer = Importer(LocalStorageBackend(config.storage_root), Manifest(conn), Courses(conn))
    staging = config.tmp_dir / uuid.uuid4().hex
    staging.mkdir(parents=True)
    try:
        for bucket, name, text in FILES:
            src = staging / name
            src.write_text(text)
            importer.import_file(src, COURSE, name, bucket)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    report = LinkStep(knowledge, Manifest(conn), config.nlm_source_cap).run(COURSE)
    log.info("Seeded %s: %d files linked", COURSE, report.added)

    learner = LearnerMemory(conn)
    evidence: dict[str, str] = {}
    for name, module, week, level in CONCEPTS:
        cid = concept_id(COURSE, name)  # the id `concepts apply` would give it
        learner.upsert_concept(Concept(cid, COURSE, name, module=module, week=week))
        if level:  # principle 4: no level without the evidence behind it
            evidence[cid] = learner.add_evidence(cid, "explained", "moderate")
            learner.set_mastery(cid, level, 0.6, [evidence[cid]])
    # The first session opens with this probe, so the chat's probe -> answer or skip flow works.
    pointers = concept_id(COURSE, "Pointers")
    ChallengeStore(conn).queue(
        pointers,
        None,
        "dev server: seeded challenge",
        proposed_level=4,
        evidence_ids=[evidence[pointers]],
    )

    now = datetime.now(UTC)
    health = HealthStore(conn)
    for provider in ("claude", "codex", "notebooklm"):
        health.set(provider, ProviderState.AVAILABLE, now, detail="dev server fake")
    ledger = Ledger(conn)
    for minutes, provider, task_type, ms in (
        (90, "claude", "explain", 4200),
        (60, "claude", "explain", 3900),
        (55, "codex", "analyze_transcript", 8100),
        (30, "notebooklm", "query", 2100),
    ):
        started = (now - timedelta(minutes=minutes)).isoformat(timespec="seconds")
        ledger.record(ModelRun(provider, task_type, started, True, "dev-fake", None, ms))
    marks = Benchmarks(conn)
    for provider, rating in (("claude", 4.0), ("codex", 3.0)):
        marks.record(provider, "explain", learner_rating=rating, format_compliance=1.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--home", required=True, type=Path, help="Scratch home (created).")
    parser.add_argument("--port", type=int, default=8765, help="Port on 127.0.0.1.")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds per fake call.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    home = args.home.expanduser().resolve()
    if home.is_relative_to((Path.home() / ".brightlearn").resolve()):
        parser.error("--home must be a scratch folder, not in ~/.brightlearn")
    config = scratch_config(home)
    ensure_home(config)

    knowledge = DevKnowledge(home / "nlm-out", args.delay)
    models = {"claude": DevModel("claude", args.delay), "codex": DevModel("codex", args.delay)}
    conn = connect(config.db_path)
    try:
        knowledge.adopt(Manifest(conn).all())
        if Courses(conn).get(COURSE) is None:
            seed(config, conn, knowledge)
    finally:
        conn.close()

    def fake_resources(cfg: Config) -> Resources:
        # Each worker its own connection, both the same fakes, as tests/conftest.py's `api`.
        return Resources(cfg, connect(cfg.db_path), knowledge, dict(models))

    import uvicorn  # here, like cli/web.py: --help shouldn't pay for the web stack

    app = create_app(config, Engine(config, open_resources=fake_resources))
    log.info("BrightLearn dev API on http://127.0.0.1:%d/ (home %s)", args.port, home)
    uvicorn.run(app, host="127.0.0.1", port=args.port, timeout_graceful_shutdown=2)


if __name__ == "__main__":
    main()
