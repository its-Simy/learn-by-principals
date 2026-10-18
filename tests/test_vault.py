import pytest

from core.memory.db import connect
from core.memory.learner import Concept, LearnerMemory
from core.memory.vault import Vault, concept_row, read_front_matter


@pytest.fixture
def mem():
    mem = LearnerMemory(connect(":memory:"), now=lambda: "2026-09-23T12:00:00+00:00")
    mem.upsert_concept(
        Concept(
            "cse220/pointer-arithmetic",
            "CSE220",
            "Pointer arithmetic",
            "Week 3",
            ["cse220/pointers"],
            ["midterm-1"],
        )
    )
    e = mem.add_evidence("cse220/pointer-arithmetic", "applied", "strong", session_id="s1")
    mem.set_mastery("cse220/pointer-arithmetic", 3, 0.75, [e])
    return mem


@pytest.fixture
def vault(tmp_path):
    return Vault(tmp_path / "memory")


def write_note(vault, mem):
    concept = mem.get_concept("cse220/pointer-arithmetic")
    return vault.write_concept_note(
        concept,
        mem.get_mastery(concept.concept_id),
        ["ptr + 1 advances one byte"],
        mem.evidence(concept.concept_id),
    )


def test_concept_note_front_matter_round_trips(vault, mem):
    path = write_note(vault, mem)

    assert path == vault.root / "concepts" / "cse220-pointer-arithmetic.md"
    concept = mem.get_concept("cse220/pointer-arithmetic")
    assert read_front_matter(path) == concept_row(concept, mem.get_mastery(concept.concept_id))
    text = path.read_text(encoding="utf-8")
    assert "# Pointer arithmetic" in text
    assert "- ptr + 1 advances one byte" in text
    assert "applied (strong)" in text
    assert vault.vault_check(mem) == []


def test_vault_check_flags_a_hand_edited_note(vault, mem):
    path = write_note(vault, mem)
    path.write_text(path.read_text(encoding="utf-8").replace("level: 3", "level: 5"))

    (mismatch,) = vault.vault_check(mem)

    assert (mismatch.field, mismatch.note, mismatch.db) == ("level", 5, 3)


def test_vault_check_flags_db_changes_since_the_note(vault, mem):
    write_note(vault, mem)
    e = mem.add_evidence("cse220/pointer-arithmetic", "transferred", "strong")
    mem.set_mastery("cse220/pointer-arithmetic", 4, 0.8, [e])

    fields = {m.field for m in vault.vault_check(mem)}
    assert {"level", "confidence", "evidence_count"} <= fields


def test_vault_check_flags_notes_for_unknown_concepts(vault, mem, tmp_path):
    path = write_note(vault, mem)
    path.write_text(
        path.read_text(encoding="utf-8").replace("cse220/pointer-arithmetic", "cse220/gone")
    )
    (mismatch,) = vault.vault_check(mem)
    assert (mismatch.field, mismatch.note) == ("concept_id", "cse220/gone")


def test_concept_without_mastery_writes_level_zero(vault, mem):
    mem.upsert_concept(Concept("cse220/unions", "CSE220", "Unions"))
    concept = mem.get_concept("cse220/unions")
    path = vault.write_concept_note(concept, None, [], [])
    assert read_front_matter(path)["level"] == 0
    assert vault.vault_check(mem) == []


def test_session_summary(vault, mem):
    session = mem.start_session("CSE220", tutor_provider="claude")
    path = vault.write_session_summary(
        session, "Worked through pointer arithmetic.", mem.evidence("cse220/pointer-arithmetic")
    )
    assert path.name == f"{session.session_id}.summary.md"
    front = read_front_matter(path)
    assert front["session_id"] == session.session_id
    assert front["tutor_provider"] == "claude"
    assert "cse220/pointer-arithmetic: applied (strong)" in path.read_text(encoding="utf-8")


def test_read_front_matter_of_plain_markdown_is_empty(tmp_path):
    path = tmp_path / "x.md"
    path.write_text("# no front matter\n", encoding="utf-8")
    assert read_front_matter(path) == {}
