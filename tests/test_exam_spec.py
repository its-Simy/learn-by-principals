"""BL-031: ExamSpec validation and the Coverage Planner."""

import pytest

from core.exams.coverage import PlanError, plan
from core.exams.spec import (
    SpecError,
    apportion,
    find_spec,
    load_spec,
    parse_spec,
    saved_spec,
)
from core.memory.learner import Concept, Mastery

SPEC = {
    "course": "cse220",
    "exam": "Midterm 1",
    "weeks": [1, 2, 3, 4, 5],
    "sources": ["syllabus", "study-guides", "lectures"],
    "formats": {"multiple_choice": 10, "short_answer": 5, "coding": 3},
    "difficulty": {"easy": 20, "medium": 50, "hard": 30},
    "mode": "realistic",
    "include": ["data representation", "pointers"],
    "exclude": ["file I/O"],
}


def spec(**changes):
    doc = {**SPEC, **changes}
    return parse_spec({k: v for k, v in doc.items() if v is not None})


# -- spec -------------------------------------------------------------------------------------


def test_master_spec_example_parses(tmp_path):
    import yaml

    path = tmp_path / "cse220-midterm1.yaml"
    path.write_text(yaml.safe_dump(SPEC))
    s = load_spec(path)
    assert (s.course, s.exam, s.slug, s.mode) == ("CSE220", "Midterm 1", "midterm-1", "realistic")
    assert s.total_questions == 18
    assert s.difficulty == {"easy": 4, "medium": 9, "hard": 5}  # 20/50/30 % of 18
    assert s.weeks == (1, 2, 3, 4, 5)


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"length": 60}, "unknown key(s) ['length']"),
        ({"exam": None}, "missing key(s) ['exam']"),
        ({"formats": {"multiple_choice": 10, "essay": 2}}, "unknown formats ['essay']"),
        ({"formats": {"multiple_choice": -1}}, "formats.multiple_choice must be a whole number"),
        ({"formats": {"multiple_choice": 0}}, "formats ask for no questions"),
        ({"formats": {"multiple_choice": 500}}, "the most is 100"),
        ({"difficulty": {"easy": 20, "medium": 50, "hard": 20}}, "difficulty adds up to 90"),
        ({"difficulty": {"easy": 20, "trivial": 80}}, "unknown difficulty ['trivial']"),
        ({"mode": "cram"}, "mode 'cram' is not one of"),
        ({"weeks": [0, 2]}, "weeks must be whole numbers from 1"),
        ({"sources": ["lectures", "vibes"]}, "unknown source(s) ['vibes']"),
        ({"include": ["Pointers"], "exclude": ["pointers"]}, "in both include and exclude"),
        ({"include": "pointers"}, "include must be a list"),
    ],
)
def test_invalid_specs_are_rejected(changes, message):
    with pytest.raises(SpecError) as info:
        spec(**changes)
    assert message in str(info.value)


def test_every_problem_is_reported_at_once():
    with pytest.raises(SpecError) as info:
        spec(length=1, mode="cram")
    assert "unknown key" in str(info.value) and "mode 'cram'" in str(info.value)


def test_difficulty_may_be_counts_that_sum_to_the_questions():
    s = spec(difficulty={"easy": 3, "medium": 10, "hard": 5})
    assert s.difficulty == {"easy": 3, "medium": 10, "hard": 5}


def test_apportion_is_exact_and_keeps_order_on_ties():
    assert apportion(18, {"a": 1, "b": 1, "c": 1}) == {"a": 6, "b": 6, "c": 6}
    assert apportion(4, {"a": 1, "b": 1, "c": 1}) == {"a": 2, "b": 1, "c": 1}
    assert apportion(10, {"a": 0.1, "b": 0.2, "c": 0.7}) == {"a": 1, "b": 2, "c": 7}
    assert sum(apportion(17, {"x": 1 / 3, "y": 1 / 3, "z": 1 / 3}).values()) == 17


# -- coverage ---------------------------------------------------------------------------------

CONCEPTS = [
    Concept("cse220/data-representation", "CSE220", "Data representation", week=1),
    Concept("cse220/bitwise-operators", "CSE220", "Bitwise operators", week=1),
    Concept("cse220/pointers", "CSE220", "Pointers", week=3),
    Concept("cse220/pointer-arithmetic", "CSE220", "Pointer arithmetic", week=4),
    Concept("cse220/file-i-o", "CSE220", "File I/O", week=5),
    Concept("cse220/processes", "CSE220", "Processes", week=9),
    Concept("cse220/linking", "CSE220", "Linking", week=None),
    Concept("cse214/stacks", "CSE214", "Stacks", week=2),
]

MASTERY = {
    "cse220/data-representation": Mastery("cse220/data-representation", 4, 0.8),
    "cse220/bitwise-operators": Mastery("cse220/bitwise-operators", 3, 0.6),
    "cse220/pointers": Mastery("cse220/pointers", 1, 0.4),
    "cse220/pointer-arithmetic": Mastery("cse220/pointer-arithmetic", 0, 0.9),
    # processes and linking: no mastery rows (level 0, confidence 0)
}


def names(p):
    return [r.concept.name for r in p.rows]


def counts(p):
    return {r.concept.name: r.n_questions for r in p.rows}


MODES = [
    # mode, include, expected questions per concept (18 total)
    (
        "realistic",
        [],
        # weeks 1, 3, 4 each weigh 1/3; week 1 is split between its two concepts
        {"Pointers": 6, "Pointer arithmetic": 6, "Bitwise operators": 3, "Data representation": 3},
    ),
    (
        "weakness",
        [],
        # 5 - level: arithmetic 5, pointers 4, bitwise 2, data rep 1 (sum 12)
        {"Pointer arithmetic": 8, "Pointers": 6, "Bitwise operators": 3, "Data representation": 1},
    ),
    (
        "challenge",
        [],
        # only level 3+
        {"Bitwise operators": 9, "Data representation": 9},
    ),
    (
        "diagnostic",
        [],
        # 1 - confidence: pointers .6, bitwise .4, data rep .2, arithmetic .1 (floored)
        {"Pointers": 8, "Bitwise operators": 6, "Data representation": 3, "Pointer arithmetic": 1},
    ),
    (
        "weakness",
        ["Processes"],
        # an included week-9 concept with no mastery joins at weight 5 (sum 17; the spare
        # question goes to the earlier week on a tie)
        {
            "Pointer arithmetic": 6,
            "Processes": 5,
            "Pointers": 4,
            "Bitwise operators": 2,
            "Data representation": 1,
        },
    ),
]


@pytest.mark.parametrize("mode, include, expected", MODES)
def test_plan_per_mode(mode, include, expected):
    s = spec(mode=mode, include=include)
    p = plan(s, CONCEPTS, MASTERY)

    assert counts(p) == expected
    assert list(expected) == names(p)  # most questions first
    # totals always match the spec
    assert p.total == s.total_questions == 18
    assert p.format_totals() == s.formats
    assert p.difficulty_totals() == s.difficulty
    for row in p.rows:
        assert sum(row.format_mix.values()) == row.n_questions
        assert sum(row.difficulty_mix.values()) == row.n_questions
    # excluded, out-of-course and out-of-week concepts never appear
    assert "File I/O" not in names(p) and "Stacks" not in names(p)
    if "Processes" not in include:
        assert "Processes" not in names(p)


@pytest.mark.parametrize("mode", ["realistic", "weakness", "challenge", "diagnostic"])
@pytest.mark.parametrize(
    "formats, difficulty",
    [
        ({"multiple_choice": 1}, {"hard": 100}),
        ({"multiple_choice": 7, "coding": 2}, {"easy": 33, "medium": 33, "hard": 34}),
        ({"short_answer": 3, "coding": 3}, {"easy": 50, "hard": 50}),
        ({"multiple_choice": 40, "short_answer": 13, "coding": 7}, {"easy": 10, "medium": 90}),
    ],
)
def test_totals_always_match(mode, formats, difficulty):
    s = spec(
        mode=mode,
        formats=formats,
        difficulty=difficulty,
        include=[],
        exclude=["file i/o", "Pointers"],
    )
    p = plan(s, CONCEPTS, MASTERY)
    assert p.total == s.total_questions
    assert p.format_totals() == s.formats
    assert p.difficulty_totals() == s.difficulty
    assert "Pointers" not in names(p) and "File I/O" not in names(p)


def test_weakness_gives_the_lowest_level_concept_the_most_questions():
    p = plan(spec(mode="weakness", include=[]), CONCEPTS, MASTERY)
    top = p.rows[0]
    assert top.concept.name == "Pointer arithmetic" and top.level == 0
    assert all(top.n_questions > r.n_questions for r in p.rows[1:])


def test_weakness_floor_keeps_mastered_concepts_in():
    mastered = {c.concept_id: Mastery(c.concept_id, 5, 1.0) for c in CONCEPTS}
    p = plan(spec(mode="weakness", include=[]), CONCEPTS, mastered)
    assert all(r.weight > 0 for r in p.rows)
    assert len(p.rows) == 4


def test_challenge_rows_are_tagged_transfer():
    p = plan(spec(mode="challenge", include=[]), CONCEPTS, MASTERY)
    assert all(r.tags == ("transfer",) and r.target_level == 4 for r in p.rows)


def test_challenge_with_nothing_at_level_3_is_an_error():
    with pytest.raises(PlanError, match="level 3"):
        plan(spec(mode="challenge", include=[]), CONCEPTS, {})


def test_unmatched_names_and_weekless_concepts_are_reported():
    p = plan(spec(include=["Pointers", "Recursion"], exclude=["Threads"]), CONCEPTS, MASTERY)
    assert p.unmatched_include == ["Recursion"]
    assert p.unmatched_exclude == ["Threads"]
    assert p.no_week == ["Linking"]


def test_include_by_concept_id_and_no_weeks_means_every_week():
    p = plan(spec(weeks=[], include=[], exclude=[]), CONCEPTS, MASTERY)
    assert set(names(p)) == {c.name for c in CONCEPTS if c.course == "CSE220"}
    q = plan(spec(weeks=[9], include=["cse220/linking"]), CONCEPTS, MASTERY)
    assert set(names(q)) == {"Processes", "Linking"}


def test_more_concepts_than_questions_drops_the_lightest():
    p = plan(spec(formats={"coding": 2}, difficulty={"hard": 100}, include=[]), CONCEPTS, {})
    assert p.total == 2 and len(p.rows) == 2


def test_find_spec_with_no_file_or_created_exam_is_a_spec_error(tmp_path):
    with pytest.raises(SpecError, match="no created CSE220 exam named 'final'"):
        find_spec(tmp_path, "CSE220", "final")


def test_saved_spec_reads_created_exams_and_never_a_file(tmp_path):
    import json

    import yaml

    spec_file = tmp_path / "midterm.yaml"
    spec_file.write_text(yaml.safe_dump(SPEC))
    exams = tmp_path / "vault/courses/CSE220/exams"
    exams.mkdir(parents=True)
    (exams / "midterm-1-20260920-100000.json").write_text(json.dumps({"spec": SPEC}))

    assert find_spec(tmp_path, "CSE220", str(spec_file)).exam == "Midterm 1"
    with pytest.raises(SpecError, match="No created CSE220 exam"):
        saved_spec(tmp_path / "vault", "CSE220", str(spec_file))
    assert saved_spec(tmp_path / "vault", "CSE220", "midterm 1").weeks == (1, 2, 3, 4, 5)
