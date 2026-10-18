"""BL-030: a disagreement produces one Challenger probe, never an average."""

import json
import sqlite3
from contextlib import contextmanager

import pytest
from typer.testing import CliRunner

from cli.app import app
from core import wiring
from core.analysis.analyzer import AnalysisReport, Analyzer, LevelChange
from core.analysis.challenge import (
    ChallengeRunner,
    ChallengeStore,
    disagreements,
    parse_estimate,
    queue_challenges,
)
from core.config import load_config
from core.context.compiler import ContextCompiler
from core.ledger.ledger import Ledger
from core.memory.db import connect
from core.memory.learner import Concept, LearnerMemory
from core.memory.vault import Vault, read_front_matter
from core.router.router import Router
from core.tutor import Tutor
from tests.fakes.fake_knowledge import FakeKnowledge
from tests.fakes.fake_models import FakeModel

POINTERS = "cse220/pointers"
ARITH = "cse220/pointer-arithmetic"


@pytest.fixture
def learner():
    mem = LearnerMemory(connect(":memory:"))
    mem.upsert_concept(Concept(POINTERS, "CSE220", "Pointers"))
    mem.upsert_concept(Concept(ARITH, "CSE220", "Pointer arithmetic"))
    mem.upsert_concept(Concept("cse214/stacks", "CSE214", "Stacks"))
    return mem


@pytest.fixture
def store(learner):
    return ChallengeStore(learner.conn)


def report(needs=(), proposals=None, session_id="s1"):
    r = AnalysisReport(session_id, "codex")
    r.needs_challenge = [LevelChange(c, cur, prop) for c, cur, prop in needs]
    r.proposals = dict(proposals or {})
    return r


# -- queueing ---------------------------------------------------------------------------------


def test_tutor_estimate_two_levels_off_queues_exactly_one_row(store):
    queued = queue_challenges(store, report(proposals={POINTERS: 1}), {POINTERS: 3})
    assert len(queued) == 1
    (row,) = store.all()
    assert (row.concept_id, row.status, row.session_id) == (POINTERS, "pending", "s1")
    assert row.reason == "tutor estimated 3, analyzer found 1"


def test_one_level_apart_queues_nothing(store):
    assert queue_challenges(store, report(proposals={POINTERS: 2}), {POINTERS: 3}) == []
    assert queue_challenges(store, report(needs=[(POINTERS, 2, 3)])) == []
    assert store.all() == []


def test_needs_challenge_queues_one_row(store):
    queue_challenges(store, report(needs=[(ARITH, 0, 3)]))
    (row,) = store.all()
    assert (row.concept_id, row.reason) == (ARITH, "analyzer proposed 0 -> 3")


def test_estimate_without_an_analyzer_finding_is_not_a_disagreement(store):
    assert disagreements(report(), {POINTERS: 5}) == []


def test_two_pending_challenges_on_one_concept_collapse_to_one(store):
    # both triggers in one session, then another disagreement in a later session
    queue_challenges(
        store, report(needs=[(POINTERS, 0, 3)], proposals={POINTERS: 3}), {POINTERS: 0}
    )
    queue_challenges(store, report(needs=[(POINTERS, 0, 4)], session_id="s2"))

    (row,) = store.all(POINTERS)
    assert row.status == "pending"
    assert row.reason == (
        "analyzer proposed 0 -> 3; tutor estimated 0, analyzer found 3; analyzer proposed 0 -> 4"
    )


def test_the_database_allows_only_one_open_challenge_per_concept(store, learner):
    store.queue(POINTERS, "s1", "a")
    with pytest.raises(sqlite3.IntegrityError):
        learner.conn.execute(
            "INSERT INTO challenges (concept_id, reason, created_at) VALUES (?, 'b', 'now')",
            (POINTERS,),
        )


def test_a_resolved_challenge_is_not_reopened_by_a_new_one(store):
    first = store.queue(POINTERS, "s1", "a")
    store.mark(first, "resolved")
    second = store.queue(POINTERS, "s2", "b")
    assert second.id != first.id
    assert [c.status for c in store.all(POINTERS)] == ["resolved", "pending"]


def test_parse_estimate():
    concepts = [
        Concept(POINTERS, "CSE220", "Pointers"),
        Concept(ARITH, "CSE220", "Pointer arithmetic"),
    ]
    text = "Pointers: 3; **Pointer arithmetic**: 1; Linked lists: 2; Pointers again: 9"
    assert parse_estimate(text, concepts) == {POINTERS: 3, ARITH: 1}


# -- the probe --------------------------------------------------------------------------------

GRADE = json.dumps(
    [
        {
            "concept": "Pointers",
            "evidence_type": "applied",
            "strength": "strong",
            "excerpt": "it would still point at the old address",
            "proposed_level": 1,
        }
    ]
)


@pytest.fixture
def models():
    return {
        "claude": FakeModel("claude", "Tutor reply.", replies=["What if p is freed first?"]),
        "codex": FakeModel("codex", GRADE),
    }


def make_tutor(learner, models, tmp_path, knowledge=None):
    ledger = Ledger(learner.conn)
    compiler = ContextCompiler(knowledge or FakeKnowledge(answer_text="Grounded."), learner)
    runner = ChallengeRunner(
        ChallengeStore(learner.conn),
        learner,
        Router(models, ledger, ["claude", "codex"]),
        Analyzer(Router(models, ledger, ["codex", "claude"]), learner),
        compiler,
    )
    router = Router(models, ledger, ["claude", "codex"])
    return Tutor(
        "CSE220", "simplifier", compiler, router, learner, Vault(tmp_path), challenges=runner
    )


def test_session_opens_with_the_probe_and_grading_resolves_it(learner, store, models, tmp_path):
    store.queue(POINTERS, "earlier", "analyzer proposed 0 -> 3")
    kp = FakeKnowledge(answer_text="Grounded.")
    tutor = make_tutor(learner, models, tmp_path, kp)
    row = tutor.start()

    opening = tutor.opening()
    assert opening == "**Challenge · Pointers**\n\nWhat if p is freed first?"
    (asked,) = models["claude"].tasks
    assert (asked.persona, asked.task_type) == ("challenger", "question_gen")
    assert "analyzer proposed 0 -> 3" in asked.user
    assert kp.conversations == [tutor.session.conversation.conversation_id]  # P66

    reply = tutor.handle("it would still point at the old address")

    assert reply.startswith("Challenge graded by codex: 1 evidence.")
    (graded,) = models["codex"].tasks
    assert graded.task_type == "analyze_transcript"
    assert "What if p is freed first?" in graded.user  # the exchange alone
    assert "Pointer arithmetic" not in graded.user
    (challenge,) = store.all()
    assert (challenge.status, challenge.question) == ("resolved", "What if p is freed first?")
    (evidence,) = learner.evidence(POINTERS)
    assert (evidence.type, evidence.session_id, evidence.source_provider) == (
        "applied",
        row.session_id,
        "codex",
    )
    assert learner.get_mastery(POINTERS) is None  # grading an exchange never applies ±1 itself
    # the probe isn't a tutoring turn: nothing for the end-of-session Analyzer to double count
    assert tutor.session.turns == []
    assert "**Learner:**" not in tutor.transcript_path.read_text(encoding="utf-8")


def test_a_resolved_challenge_is_not_asked_again(learner, store, models, tmp_path):
    store.queue(POINTERS, "earlier", "r")
    first = make_tutor(learner, models, tmp_path)
    first.start()
    first.opening()
    first.handle("it would still point at the old address")
    first.handle("/end")

    second = make_tutor(learner, models, tmp_path)
    second.start()
    assert second.opening() is None
    assert len([t for t in models["claude"].tasks if t.persona == "challenger"]) == 1


def test_one_probe_per_concept_then_tutoring(learner, store, models, tmp_path):
    store.queue(POINTERS, "earlier", "r1")
    store.queue(ARITH, "earlier", "r2")
    store.queue("cse214/stacks", "earlier", "other course")
    models["claude"].replies = ["Q on pointers?", "Q on arithmetic?"]
    tutor = make_tutor(learner, models, tmp_path)
    tutor.start()

    assert "Q on pointers?" in tutor.opening()
    assert "Q on arithmetic?" in tutor.handle("it would still point at the old address")
    assert tutor.handle("no idea").endswith("Now, what shall we work on?")
    assert tutor.handle("What is a pointer?") == "Tutor reply."
    assert [c.status for c in store.all()] == ["resolved", "resolved", "pending"]


def test_skip_defers_and_the_same_question_comes_back(learner, store, models, tmp_path):
    store.queue(POINTERS, "earlier", "r")
    tutor = make_tutor(learner, models, tmp_path)
    tutor.start()
    tutor.opening()
    assert tutor.handle("/skip") == "1 challenge(s) deferred to a later session."
    assert tutor.handle("What is a pointer?") == "Tutor reply."
    (challenge,) = store.all()
    assert challenge.status == "asked"

    again = make_tutor(learner, models, tmp_path)
    again.start()
    assert again.opening() == "**Challenge · Pointers**\n\nWhat if p is freed first?"
    assert len([t for t in models["claude"].tasks if t.persona == "challenger"]) == 1


def test_failed_grading_leaves_the_challenge_to_ask_again(learner, store, tmp_path):
    models = {"claude": FakeModel("claude", "Q?"), "codex": FakeModel("codex", "no JSON here")}
    store.queue(POINTERS, "earlier", "r")
    tutor = make_tutor(learner, models, tmp_path)
    tutor.start()
    tutor.opening()
    assert "will be asked again next session" in tutor.handle("my answer")
    assert store.all()[0].status == "asked"
    assert learner.evidence(POINTERS) == []


# -- end of session ---------------------------------------------------------------------------


def test_end_of_session_estimate_disagreement_queues_a_challenge(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BRIGHTLEARN_VAULT", str(tmp_path / "memory"))
    conn = connect(load_config().db_path)
    LearnerMemory(conn).upsert_concept(Concept(POINTERS, "CSE220", "Pointers"))
    conn.close()
    finding = json.dumps(
        [
            {
                "concept": "Pointers",
                "evidence_type": "explained",
                "strength": "weak",
                "excerpt": "What is a pointer?",
                "proposed_level": 1,
            }
        ]
    )
    models = {
        "claude": FakeModel("claude", replies=["A pointer holds an address.", "Pointers: 4"]),
        "codex": FakeModel("codex", finding),
    }

    @contextmanager
    def fake_open_knowledge(config, conn):
        yield FakeKnowledge()

    monkeypatch.setattr(wiring, "open_knowledge", fake_open_knowledge)
    monkeypatch.setattr(wiring, "open_model", lambda name, config: models[name])

    result = CliRunner().invoke(
        app, ["tutor", "--course", "CSE220"], input="What is a pointer?\n/end\n"
    )

    assert result.exit_code == 0, result.output
    assert "1 challenge(s) queued for next session." in result.output
    assert models["claude"].tasks[-1].task_type == "tutor_estimate"
    conn = connect(load_config().db_path)
    (challenge,) = ChallengeStore(conn).all()
    assert challenge.reason == "tutor estimated 4, analyzer found 1"
    (summary,) = (tmp_path / "memory" / "sessions").glob("*.summary.md")
    assert read_front_matter(summary)["tutor_estimate"] == "Pointers: 4"

    # the next session opens with the probe
    models["claude"].replies = ["Predict: what does *p give after p++?"]
    nxt = CliRunner().invoke(app, ["tutor", "--course", "CSE220"], input="/skip\n/end\n")
    assert nxt.exit_code == 0, nxt.output
    assert "Predict: what does *p give after p++?" in nxt.output


# -- BL-040 (P72): the outcome of a probe ----------------------------------------------------


def grade_reply(proposed, kind="applied", strength="strong"):
    return json.dumps(
        [
            {
                "concept": "Pointers",
                "evidence_type": kind,
                "strength": strength,
                "excerpt": "it would still point at the old address",
                "proposed_level": proposed,
            }
        ]
    )


def run_probe(learner, models, tmp_path):
    tutor = make_tutor(learner, models, tmp_path)
    tutor.start()
    tutor.opening()
    reply = tutor.handle("it would still point at the old address")
    return tutor, reply


def test_queueing_keeps_the_analyzers_proposal_and_its_evidence(store, learner):
    e1 = learner.add_evidence(POINTERS, "applied", "strong")
    r = report(needs=[(POINTERS, 0, 3)])
    r.support = {POINTERS: [e1]}
    queue_challenges(store, r)
    e2 = learner.add_evidence(POINTERS, "transferred", "strong")
    later = report(needs=[(POINTERS, 0, 4)], session_id="s2")
    later.support = {POINTERS: [e2]}
    queue_challenges(store, later)

    (row,) = store.all()
    assert row.proposed_level == 4  # the latest proposal
    assert json.loads(row.evidence_ids) == [e1, e2]


def test_upheld_probe_sets_the_full_proposed_level_citing_both(learner, store, tmp_path):
    original = learner.add_evidence(POINTERS, "applied", "strong", session_id="earlier")
    store.queue(POINTERS, "earlier", "analyzer proposed 0 -> 3", 3, [original])
    models = {"claude": FakeModel("claude", "Q?"), "codex": FakeModel("codex", grade_reply(3))}

    tutor, reply = run_probe(learner, models, tmp_path)

    mastery = learner.get_mastery(POINTERS)
    assert mastery.level == 3  # the whole jump, not +1 and never an average
    change = learner.mastery_history(POINTERS)[-1]
    assert (change.old_level, change.new_level, change.changed_by) == (None, 3, "challenger")
    exchange = [e.evidence_id for e in learner.evidence(POINTERS) if e.session_id != "earlier"]
    assert change.evidence_ids == [original, *exchange]
    assert "Upheld: Pointers is now level 3." in reply
    assert store.all()[0].status == "resolved"


def test_failed_probe_writes_its_evidence_only(learner, store, tmp_path):
    original = learner.add_evidence(POINTERS, "applied", "strong", session_id="earlier")
    learner.set_mastery(POINTERS, 1, 0.6, [original])
    store.queue(POINTERS, "earlier", "analyzer proposed 1 -> 4", 4, [original])
    models = {
        "claude": FakeModel("claude", "Q?"),
        "codex": FakeModel("codex", grade_reply(1, "failed", "strong")),
    }

    tutor, reply = run_probe(learner, models, tmp_path)

    assert learner.get_mastery(POINTERS).level == 1  # no level change
    assert len(learner.mastery_history(POINTERS)) == 1
    assert [e.type for e in learner.evidence(POINTERS)] == ["applied", "failed"]
    assert store.all()[0].status == "resolved"  # needs_challenge cleared
    assert "Upheld" not in reply


def test_a_partial_answer_below_the_challenged_level_is_not_upheld(learner, store, tmp_path):
    store.queue(POINTERS, "earlier", "analyzer proposed 0 -> 3", 3, [])
    models = {"claude": FakeModel("claude", "Q?"), "codex": FakeModel("codex", grade_reply(2))}
    run_probe(learner, models, tmp_path)
    assert learner.get_mastery(POINTERS) is None
    assert store.all()[0].status == "resolved"


def test_an_estimate_challenge_never_changes_a_level(learner, store, tmp_path):
    store.queue(POINTERS, "earlier", "tutor estimated 4, analyzer found 1")  # no proposal
    models = {"claude": FakeModel("claude", "Q?"), "codex": FakeModel("codex", grade_reply(4))}
    run_probe(learner, models, tmp_path)
    assert learner.get_mastery(POINTERS) is None
    assert [e.type for e in learner.evidence(POINTERS)] == ["applied"]


def test_a_downward_proposal_is_never_applied_by_a_probe(learner, store, tmp_path):
    e = learner.add_evidence(POINTERS, "transferred", "strong")
    learner.set_mastery(POINTERS, 4, 0.8, [e])
    store.queue(POINTERS, "earlier", "analyzer proposed 4 -> 1", 1, [e])
    models = {"claude": FakeModel("claude", "Q?"), "codex": FakeModel("codex", grade_reply(4))}
    run_probe(learner, models, tmp_path)
    assert learner.get_mastery(POINTERS).level == 4
