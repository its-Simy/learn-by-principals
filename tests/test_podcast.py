"""BL-034: the adaptive podcast brief and `brightlearn podcast`."""

import json
from contextlib import contextmanager

import pytest
from typer.testing import CliRunner

from cli.app import app
from core import wiring
from core.config import load_config
from core.exams.spec import parse_spec
from core.memory.db import Courses, connect
from core.memory.learner import Concept, LearnerMemory
from core.memory.vault import Vault
from core.podcast.compiler import WORD_CAP, build_podcast_context, compile_podcast_context, words
from core.podcast.episodes import PodcastStore
from tests.fakes.fake_knowledge import FakeKnowledge

NAMES = ["Data representation", "Bitwise operators", "Pointers", "Pointer arithmetic", "Structs"]


@pytest.fixture
def learner():
    mem = LearnerMemory(connect(":memory:"))
    for week, name in enumerate(NAMES, start=1):
        mem.upsert_concept(
            Concept(f"cse220/{name.lower().replace(' ', '-')}", "CSE220", name, week=week)
        )
    return mem


def cid(name):
    return f"cse220/{name.lower().replace(' ', '-')}"


def set_level(learner, name, level, retention=None, confidence=0.8):
    e = learner.add_evidence(cid(name), "applied", "strong")
    learner.set_mastery(cid(name), level, confidence, [e])
    if retention is not None:
        learner.conn.execute(
            "UPDATE mastery SET retention_confidence = ? WHERE concept_id = ?",
            (retention, cid(name)),
        )


def focus(ctx):
    return [c.name for c, _ in ctx.focus]


def test_two_mastery_states_give_different_focus_lists(learner):
    set_level(learner, "Data representation", 3)
    set_level(learner, "Bitwise operators", 2)
    before = build_podcast_context("CSE220", None, learner)

    # a week later: pointers mastered, bitwise slipped
    set_level(learner, "Pointers", 4, retention=0.9)
    set_level(learner, "Pointer arithmetic", 4, retention=0.8)
    set_level(learner, "Structs", 3)
    after = build_podcast_context("CSE220", None, learner)

    assert focus(before)[:3] == ["Pointer arithmetic", "Pointers", "Structs"]  # unseen first
    assert focus(after)[0] == "Bitwise operators"
    assert focus(before) != focus(after)
    assert before.text != after.text
    assert [c.name for c in after.skip] == ["Pointer arithmetic", "Pointers"]


@pytest.mark.parametrize(
    "level, retention, skipped",
    [(5, 0.95, True), (4, 0.7, True), (4, 0.69, False), (3, 1.0, False), (0, None, False)],
)
def test_skip_list_needs_level_4_and_retention_0_7(learner, level, retention, skipped):
    if level:
        set_level(learner, "Pointers", level, retention=retention)
    ctx = build_podcast_context("CSE220", None, learner)
    assert ("Pointers" in [c.name for c in ctx.skip]) is skipped
    assert all(learner.get_mastery(c.concept_id).level >= 4 for c in ctx.skip)
    assert ("Pointers" in focus(ctx)) is not skipped


def test_exam_scope_and_framing(learner):
    spec = parse_spec(
        {
            "course": "CSE220",
            "exam": "Midterm 1",
            "weeks": [1, 2, 3],
            "formats": {"multiple_choice": 10, "coding": 2},
            "difficulty": {"easy": 50, "hard": 50},
            "mode": "challenge",  # ignored for the podcast: focus is always weakest-first
            "exclude": ["Bitwise operators"],
        }
    )
    set_level(learner, "Data representation", 2)
    ctx = build_podcast_context("CSE220", spec, learner)

    assert focus(ctx) == ["Pointers", "Data representation"]
    assert (
        "Midterm 1, which covers weeks 1, 2, 3 (10 multiple choice, 2 coding questions)" in ctx.text
    )
    assert ctx.text.startswith("# Audio Overview brief: CSE220 · Midterm 1")


def test_misconceptions_and_profile_come_from_the_vault(learner, tmp_path):
    vault = Vault(tmp_path)
    learner.add_evidence(
        cid("Pointer arithmetic"), "misconception", "moderate", excerpt_ref="p + 1 adds one byte"
    )
    pointers = learner.get_concept(cid("Pointers"))
    vault.write_concept_note(pointers, None, ["*p and p are the same thing"], [])
    (tmp_path / "learner").mkdir()
    (tmp_path / "learner/profile.md").write_text(
        "---\nkind: profile\n---\n# Me\n- examples first\n- analogies to cooking\n"
    )

    text = compile_podcast_context("CSE220", None, learner, vault)

    assert '"p + 1 adds one byte" (Pointer arithmetic)' in text
    assert '"*p and p are the same thing" (Pointers)' in text
    assert "examples first; analogies to cooking" in text
    closing = (
        "Close with two short thought experiments on Bitwise operators and Data representation"
    )
    assert f"## How to end\n{closing}" in text


def test_word_cap_is_enforced(tmp_path):
    mem = LearnerMemory(connect(":memory:"))
    vault = Vault(tmp_path)
    for i in range(40):
        name = f"Concept number {i} with a deliberately long descriptive name about memory layout"
        mem.upsert_concept(Concept(f"cse220/c{i}", "CSE220", name, week=1))
        e = mem.add_evidence(
            f"cse220/c{i}", "misconception", "weak", excerpt_ref=" ".join(["wrong"] * 40) + str(i)
        )
        if i % 2:
            mem.set_mastery(f"cse220/c{i}", 5, 0.9, [e])
    (tmp_path / "learner").mkdir()
    (tmp_path / "learner/profile.md").write_text(" ".join(["verbose"] * 500))

    text = compile_podcast_context("CSE220", None, mem, vault)

    assert words(text) <= WORD_CAP
    assert "## Dwell on" in text and "## How to end" in text


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BRIGHTLEARN_VAULT", str(tmp_path / "vault"))
    monkeypatch.setenv("BRIGHTLEARN_TERM", "Fall-2026")
    conn = connect(load_config().db_path)
    Courses(conn).add("CSE220", "Systems Fundamentals", "Fall-2026")
    mem = LearnerMemory(conn)
    for week, name in enumerate(NAMES, start=1):
        mem.upsert_concept(Concept(cid(name), "CSE220", name, week=week))
    conn.close()
    kp = FakeKnowledge(out_dir=tmp_path / "downloads")

    @contextmanager
    def fake_open_knowledge(config, conn):
        yield kp

    monkeypatch.setattr(wiring, "open_knowledge", fake_open_knowledge)
    return kp, tmp_path


def test_cli_generates_audio_saves_both_files_and_records_the_episode(cli_env):
    kp, tmp = cli_env
    result = CliRunner().invoke(app, ["podcast", "--course", "cse220", "--length", "long"])

    assert result.exit_code == 0, result.output
    ((kind, (instructions, fmt, length)),) = [c for c in kp.calls if c[0] == "generate_audio"]
    assert (fmt, length) == ("deep-dive", "long")
    folder = tmp / "home/courses/Fall-2026/CSE220/_generated"
    (audio,) = folder.glob("*-podcast.mp3")
    (brief,) = folder.glob("*-podcast.md")
    assert audio.stem == brief.stem  # side by side
    assert brief.read_text() == instructions
    conn = connect(load_config().db_path)
    (episode,) = PodcastStore(conn).all("CSE220")
    assert episode.audio_path == str(audio) and episode.instruction_path == str(brief)
    assert episode.concepts == [
        cid(n)
        for n in [
            "Bitwise operators",
            "Data representation",
            "Pointer arithmetic",
            "Pointers",
            "Structs",
        ]
    ]


def test_cli_exam_by_name_uses_the_created_exams_spec(cli_env):
    kp, tmp = cli_env
    exams = tmp / "vault/courses/CSE220/exams"
    exams.mkdir(parents=True)
    spec = {
        "course": "CSE220",
        "exam": "Midterm 1",
        "formats": {"coding": 1},
        "difficulty": {"hard": 1},
        "mode": "realistic",
        "weeks": [3],
        "sources": [],
        "include": [],
        "exclude": [],
    }
    (exams / "midterm-1-20260920-100000.json").write_text(
        json.dumps({"spec": spec, "questions": []})
    )

    result = CliRunner().invoke(app, ["podcast", "--course", "CSE220", "--exam", "midterm1"])

    assert result.exit_code == 0, result.output
    ((_, (instructions, _, _)),) = [c for c in kp.calls if c[0] == "generate_audio"]
    assert "prepares for Midterm 1, which covers weeks 3" in instructions
    assert "Focus: Pointers" in result.output


def test_cli_unknown_exam_is_a_usage_error(cli_env):
    result = CliRunner().invoke(app, ["podcast", "--course", "CSE220", "--exam", "final"])
    assert result.exit_code == 2
