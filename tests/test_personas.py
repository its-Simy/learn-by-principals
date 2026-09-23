import pytest

from core import personas
from core.personas import SECTIONS, MissingAnchor, PersonaError, load, render

ALL = ["analogist", "analyzer", "challenger", "critic", "exemplar", "questioner", "simplifier"]


def test_all_seven_parse():
    assert personas.list() == ALL
    for name in ALL:
        persona = load(name)
        assert persona.name == name
        assert persona.group in ("teaching", "assessment")
        assert persona.task_types
        assert set(SECTIONS) <= set(persona.sections)
        assert len(persona.rules) >= 3


@pytest.mark.parametrize("name", [n for n in ALL if n != "analogist"])
def test_render_includes_every_rules_bullet(name):
    persona = load(name)
    prompt = render(persona, {"course": "CSE220"})
    for rule in persona.rules:
        assert rule in prompt
    assert "CSE220" in prompt


def test_analogist_refuses_without_a_level_3_anchor():
    analogist = load("analogist")
    assert analogist.min_anchor_level == 3
    with pytest.raises(MissingAnchor):
        render(analogist, {})
    with pytest.raises(MissingAnchor):
        render(analogist, {"anchors": [{"concept": "Arrays", "level": 2}]})


def test_analogist_renders_with_its_anchor_and_every_rule():
    analogist = load("analogist")
    prompt = render(
        analogist,
        {"anchors": [{"concept": "Arrays", "level": 3}, {"concept": "Bits", "level": 1}]},
    )
    assert "- Arrays (level 3)" in prompt
    assert "Bits" not in prompt  # below the anchor level
    for rule in analogist.rules:
        assert rule in prompt


def test_unknown_persona(tmp_path):
    with pytest.raises(PersonaError):
        load("comedian")


def test_missing_section_is_rejected(tmp_path):
    (tmp_path / "broken.md").write_text(
        "---\nname: broken\ngroup: teaching\ntask_types: [explain]\n---\n## Goal\nx\n"
    )
    with pytest.raises(PersonaError, match="missing sections"):
        load("broken", tmp_path)
