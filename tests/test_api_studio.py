"""BL-046: the Studio routes (concepts, exams, podcasts) on the fakes."""

import json
import threading

import pytest
import yaml

from api.schemas.studio import QUESTION_KEYS, RESULT_KEYS
from core.exams.paper import LETTERS
from core.exams.spec import parse_spec
from core.memory.db import Courses, connect
from core.memory.learner import Concept, LearnerMemory
from core.podcast.episodes import PodcastStore
from tests.fakes.fake_exam import FakeCritic, FakeQuestioner
from tests.test_exam_cli import SPEC
from tests.test_seeding import canned_answer

COURSE = "CSE220"
BASE = f"/api/courses/{COURSE.lower()}"  # routes upper-case the code, as the CLI does


@pytest.fixture
def studio(api, config):
    """``(client, knowledge, models, engine, learner)``: the ``api`` fixture with the exam fakes
    on the jobs worker, and CSE220 holding two concepts as tests/test_exam_cli.py sets them up."""
    client, kp, models, engine = api
    exam_models = {"claude": FakeQuestioner("claude"), "codex": FakeCritic("codex")}
    engine.jobs.worker.call(lambda r: r.providers.update(exam_models))  # on the worker's thread
    models.update(exam_models)
    conn = connect(config.db_path)
    Courses(conn).add(COURSE, "Systems Fundamentals", "Fall-2026")
    learner = LearnerMemory(conn)
    learner.upsert_concept(Concept("cse220/pointers", COURSE, "Pointers", week=1))
    learner.upsert_concept(Concept("cse220/bitwise-operators", COURSE, "Bitwise operators", week=2))
    evidence = learner.add_evidence("cse220/pointers", "explained", "moderate")
    learner.set_mastery("cse220/pointers", 1, 0.6, [evidence])
    yield client, kp, models, engine, learner
    conn.close()


def run_job(client, engine, response) -> dict:
    """The job a route queued, once the jobs worker has run it."""
    assert response.status_code == 200, response.text
    engine.drain()
    return client.get(f"/api/jobs/{response.json()['id']}").json()


def park(engine) -> threading.Event:
    """Hold the jobs worker until the event is set, so a test can act while a job is queued."""
    gate = threading.Event()
    engine.jobs.worker.submit(lambda r: gate.wait(5))
    return gate


def keys(value) -> set[str]:
    """Every key anywhere in a JSON value."""
    if isinstance(value, dict):
        return set(value).union(*(keys(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(keys(v) for v in value))
    return set()


# -- concepts ------------------------------------------------------------------------------


def test_concepts_with_mastery_and_evidence(studio):
    client, *_ = studio
    by_id = {c["concept_id"]: c for c in client.get(f"{BASE}/concepts").json()}
    assert set(by_id) == {"cse220/pointers", "cse220/bitwise-operators"}
    pointers = by_id["cse220/pointers"]
    assert (pointers["name"], pointers["week"], pointers["level"]) == ("Pointers", 1, 1)
    assert pointers["confidence"] == 0.6 and pointers["evidence_count"] == 1
    assert pointers["last_evidence_at"]
    assert pointers["status"] == "active"
    bitwise = by_id["cse220/bitwise-operators"]
    assert (bitwise["level"], bitwise["evidence_count"]) == (0, 0)
    assert bitwise["last_evidence_at"] is None

    (evidence,) = client.get(
        f"{BASE}/concepts/evidence", params={"concept_id": "cse220/pointers"}
    ).json()
    assert (evidence["type"], evidence["strength"]) == ("explained", "moderate")
    missing = client.get(f"{BASE}/concepts/evidence", params={"concept_id": "cse221/pointers"})
    assert missing.status_code == 404
    assert client.get("/api/courses/cse999/concepts").status_code == 404


def test_retired_concepts_only_when_asked(studio):
    client, *_, learner = studio
    learner.retire_concept("cse220/bitwise-operators")

    active = client.get(f"{BASE}/concepts").json()
    every = client.get(f"{BASE}/concepts", params={"include_retired": "true"}).json()

    assert [c["concept_id"] for c in active] == ["cse220/pointers"]
    assert {c["concept_id"]: c["status"] for c in every} == {
        "cse220/bitwise-operators": "retired",
        "cse220/pointers": "active",
    }


def test_seed_job_writes_a_draft(studio, config):
    client, kp, _, engine, _ = studio
    kp.answer_text = canned_answer()

    job = run_job(client, engine, client.post(f"{BASE}/concepts/seed"))

    assert job["kind"] == "seed" and job["status"] == "done", job["error"]
    result = job["result"]
    assert result["count"] == 2 and result["previous"] is None and result["diff"] == ""
    draft = config.vault_root / "courses" / COURSE / result["draft"]
    assert "reviewed: false" in draft.read_text()
    again = run_job(client, engine, client.post(f"{BASE}/concepts/seed"))["result"]
    assert again["previous"] == result["draft"] and again["draft"] != result["draft"]
    assert draft.exists()  # an earlier draft is never overwritten (P65)


def test_seed_is_refused_while_a_session_is_open(studio):
    client, kp, _, engine, learner = studio
    session = learner.start_session(COURSE)

    response = client.post(f"{BASE}/concepts/seed")

    assert response.status_code == 409
    assert response.json()["code"] == "session_open"
    assert response.json()["session_id"] == session.session_id
    assert engine.jobs.all(COURSE) == [] and kp.queries == []


def seed_draft(client, engine, kp) -> str:
    kp.answer_text = canned_answer()
    return run_job(client, engine, client.post(f"{BASE}/concepts/seed"))["result"]["draft"]


def test_review_a_draft_then_apply_it(studio):
    client, kp, _, engine, _ = studio
    name = seed_draft(client, engine, kp)
    assert client.get(f"{BASE}/concepts/drafts").json() == [
        {"name": name, "reviewed": False, "latest": True}
    ]

    refused = client.post(f"{BASE}/concepts/apply")
    assert refused.status_code == 422 and "reviewed: false" in refused.json()["detail"]

    text = client.get(f"{BASE}/concepts/drafts/{name}").json()["text"]
    saved = client.put(
        f"{BASE}/concepts/drafts/{name}",
        json={"text": text.replace("reviewed: false", "reviewed: true")},
    )
    assert saved.json() == {"name": name, "reviewed": True, "latest": True}

    applied = client.post(f"{BASE}/concepts/apply", json={"draft": name}).json()
    # Pointers was already there (updated: module and week); Bitwise operators isn't in the
    # draft, so it is retired, never deleted.
    assert applied == {
        "draft": name,
        "added": 1,
        "updated": 1,
        "unchanged": 0,
        "retired": 1,
        "retired_names": ["Bitwise operators"],
        "unknown_prerequisites": [],
    }
    again = client.post(f"{BASE}/concepts/apply").json()  # the newest draft, by default
    assert (again["unchanged"], again["added"], again["retired"]) == (2, 0, 0)
    names = sorted(c["name"] for c in client.get(f"{BASE}/concepts").json())
    assert names == ["Data representation", "Pointers"]


def test_a_draft_apply_could_not_load_is_refused_on_save(studio, config):
    client, kp, _, engine, _ = studio
    name = seed_draft(client, engine, kp)
    url = f"{BASE}/concepts/drafts/{name}"
    before = client.get(url).json()["text"]

    for text, says in [
        ("course: [CSE220", "Not valid YAML"),
        (before.replace("course: CSE220", "course: CSE221"), "keep `course: CSE220`"),
        ("course: CSE220\nconcepts:\n- module: Bits\n", "needs a name"),
        ("course: CSE220\nconcepts:\n- name: X\n  prerequisites: Y\n", "list of names"),
        ("course: CSE220\nconcepts:\n- name: X\n  module: [Bits, Memory]\n", "module must"),
        ("course: CSE220\nconcepts:\n- name: X\n  week: three\n", "week must"),
        ("course: CSE220\nconcepts:\n- name: X\n  week: true\n", "week must"),
    ]:
        response = client.put(url, json={"text": text})
        assert response.status_code == 422, text
        assert says in response.json()["detail"]
    assert client.get(url).json()["text"] == before

    # Apply reads week 3.0 as week 3, so the editor takes it too.
    edited = before.replace("week: 3", "week: 3.0").replace("reviewed: false", "reviewed: true")
    assert client.put(url, json={"text": edited}).status_code == 200
    assert client.post(f"{BASE}/concepts/apply").status_code == 200
    by_id = {c["concept_id"]: c for c in client.get(f"{BASE}/concepts").json()}
    assert by_id["cse220/pointers"]["week"] == 3

    folder = config.vault_root / "courses" / COURSE
    (folder / "notes.yaml").write_text("course: CSE220\n")
    for bad in ("%2E%2E", "notes.yaml", "concepts.draft.20990101-000000.yaml"):
        assert client.get(f"{BASE}/concepts/drafts/{bad}").status_code == 404, bad
        assert client.put(f"{BASE}/concepts/drafts/{bad}", json={"text": before}).status_code == 404
    assert client.post(f"{BASE}/concepts/apply", json={"draft": ".."}).status_code == 404


def test_a_drafts_diff_against_the_one_before(studio):
    client, kp, _, engine, _ = studio
    first = seed_draft(client, engine, kp)
    kp.answer_text = canned_answer().replace('"week": 3', '"week": 4')
    second = run_job(client, engine, client.post(f"{BASE}/concepts/seed"))["result"]

    assert client.get(f"{BASE}/concepts/drafts/{first}/diff").json() == {"text": ""}
    diff = client.get(f"{BASE}/concepts/drafts/{second['draft']}/diff").json()["text"]
    assert diff == second["diff"]  # what the seed job showed, again after a restart
    assert f"--- {first}" in diff and "-  week: 3" in diff and "+  week: 4" in diff
    assert client.get(f"{BASE}/concepts/drafts/%2E%2E/diff").status_code == 404


def test_apply_with_no_draft_is_404(studio):
    client, *_ = studio
    assert client.post(f"{BASE}/concepts/apply").status_code == 404
    assert client.get(f"{BASE}/concepts/drafts").json() == []


# -- exams ---------------------------------------------------------------------------------


def create_exam(client, engine, spec=SPEC) -> dict:
    job = run_job(client, engine, client.post(f"{BASE}/exams", json={"spec_yaml": yaml.dump(spec)}))
    assert job["status"] == "done", job["error"]
    return job["result"]


def exam_file(config, exam_id) -> dict:
    path = config.vault_root / "courses" / COURSE / "exams" / f"{exam_id}.json"
    return json.loads(path.read_text())


def take_all(client, config, exam_id, wrong=lambda q: q["difficulty"] == "hard") -> list[dict]:
    """Answer every question through the API, right unless ``wrong(q)``; MC by letter. The
    key comes from the file: the API never shows it."""
    key = {q["index"]: q for q in exam_file(config, exam_id)["questions"]}
    url = f"{BASE}/exams/{exam_id}/take"
    state = client.post(url).json()
    shown = []
    while (question := state["question"]) is not None:
        shown.append(question)
        q = key[question["index"]]
        if q["format"] == "multiple_choice":
            right = q["options"].index(q["answer"])
            reply = LETTERS[(right + 1) % 4] if wrong(q) else LETTERS[right].lower()
        else:
            reply = "nope" if wrong(q) else "correct: it holds an address"
        response = client.post(f"{url}/answer", json={"reply": reply})
        assert response.status_code == 200, response.text
        state = response.json()
    return shown


def test_exam_create_take_grade(studio, config):
    client, _, models, engine, _ = studio

    result = create_exam(client, engine)

    assert result["questions"] == 6 and result["planned"] == 6
    assert result["critiqued"] is True and result["critic_provider"] == "codex"
    assert result["generator_providers"] == ["claude"]
    exam_id = result["exam_id"]
    (listed,) = client.get(f"{BASE}/exams").json()
    assert listed == client.get(f"{BASE}/exams/{exam_id}").json()
    assert (listed["id"], listed["exam"], listed["mode"]) == (exam_id, "Midterm 1", "realistic")
    assert (listed["questions"], listed["review"], listed["attempts"]) == (6, "critiqued", [])

    shown = take_all(client, config, exam_id)
    assert len(shown) == 6
    finished = client.post(f"{BASE}/exams/{exam_id}/take/finish").json()
    assert finished["finished"] is True and finished["answered"] == 6
    assert finished["question"] is None

    graded = run_job(client, engine, client.post(f"{BASE}/exams/{exam_id}/grade"))

    assert graded["kind"] == "exam_grade" and graded["status"] == "done", graded["error"]
    report = graded["result"]
    assert (report["correct"], report["graded"], len(report["new_evidence"])) == (4, 6, 6)
    assert {s["concept_id"] for s in report["scores"]} <= {
        "cse220/pointers",
        "cse220/bitwise-operators",
    }
    assert sorted(exam_evidence(config)) == sorted(report["new_evidence"])
    (attempt,) = client.get(f"{BASE}/exams/{exam_id}").json()["attempts"]
    assert (attempt["answered"], attempt["graded"], attempt["correct"]) == (6, 6, 4)
    assert [t.task_type for t in models["codex"].tasks] == ["critique", "grade"]

    again = run_job(client, engine, client.post(f"{BASE}/exams/{exam_id}/grade"))["result"]
    assert (again["new_evidence"], again["already_graded"]) == ([], 6)
    assert sorted(exam_evidence(config)) == sorted(report["new_evidence"])


def exam_evidence(config) -> list[str]:
    conn = connect(config.db_path)
    rows = conn.execute("SELECT evidence_id FROM evidence WHERE session_id LIKE 'exam:%'")
    ids = [r["evidence_id"] for r in rows]
    conn.close()
    return ids


def test_grade_refuses_an_attempt_not_handed_in(studio):
    """A doomed grade job would hold up every take step on the course until its turn came."""
    client, _, _, engine, _ = studio
    exam_id = create_exam(client, engine)["exam_id"]
    grade = f"{BASE}/exams/{exam_id}/grade"

    never = client.post(grade)
    client.post(f"{BASE}/exams/{exam_id}/take")
    unfinished = client.post(grade)

    assert never.status_code == 422 and "hasn't been taken" in never.json()["detail"]
    assert unfinished.status_code == 422 and "Attempt 1 isn't finished" in unfinished.text
    assert [j.kind for j in engine.jobs.all(COURSE)] == ["exam_create"]


def test_take_never_shows_the_answer(studio, config):
    client, _, _, engine, _ = studio
    exam_id = create_exam(client, engine)["exam_id"]

    state = client.post(f"{BASE}/exams/{exam_id}/take").json()

    assert (state["attempt"], state["resumed"], state["total"]) == (1, False, 6)
    question = state["question"]
    assert set(question) == set(QUESTION_KEYS)
    assert not {"answer", "rubric", "provider"} & set(question)
    stored = exam_file(config, exam_id)["questions"][question["index"]]
    assert stored["answer"] and stored["rubric"]  # they exist; the API just doesn't send them
    resumed = client.post(f"{BASE}/exams/{exam_id}/take").json()
    assert (resumed["attempt"], resumed["resumed"]) == (1, True)


def test_no_response_but_results_carries_the_key(studio, config):
    """Answers, rubrics, authors and grader feedback stay in the file, whatever the step."""
    client, _, _, engine, _ = studio
    exam_id = create_exam(client, engine)["exam_id"]
    exam, take = f"{BASE}/exams/{exam_id}", f"{BASE}/exams/{exam_id}/take"
    steps = [client.post(take), client.get(take)]
    first = steps[0].json()["question"]
    wrong = "A" if first["format"] == "multiple_choice" else "nope"  # the fake's key is B
    steps.append(client.post(f"{take}/answer", json={"reply": wrong}))
    steps.append(client.post(f"{take}/skip"))
    steps.append(client.post(f"{take}/finish"))
    run_job(client, engine, client.post(f"{exam}/grade"))
    (grade,) = exam_file(config, exam_id)["attempts"][0]["grades"].values()
    assert grade["feedback"]  # there is feedback to leak, once an attempt is graded
    steps += [client.get(exam), client.get(f"{BASE}/exams"), client.get(take)]
    steps.append(client.post(take))  # attempt 2, with attempt 1 graded
    steps.append(client.post(f"{take}/answer", json={"reply": wrong}))
    steps.append(client.post(f"{take}/skip"))
    steps.append(client.post(f"{take}/finish"))

    assert [r.status_code for r in steps] == [200] * len(steps)
    for response in steps:
        assert not {"answer", "rubric", "provider", "feedback"} & keys(response.json())
        assert "Mentions the key idea." not in response.text  # the fake's rubric
        assert "the reference answer" not in response.text  # its open answers' key
        assert "The answer is" not in response.text  # the MC grader's feedback


def test_the_attempt_can_be_read_without_opening_one(studio, config):
    client, _, _, engine, _ = studio
    exam_id = create_exam(client, engine)["exam_id"]
    take = f"{BASE}/exams/{exam_id}/take"

    assert client.get(take).json() == {
        "attempt": None,
        "resumed": False,
        "total": 6,
        "answered": 0,
        "skipped": 0,
        "finished": False,
        "question": None,
    }
    assert exam_file(config, exam_id)["attempts"] == []  # reading opened nothing
    opened = client.post(take).json()
    read = client.get(take).json()
    assert read == {**opened, "resumed": True}
    client.post(f"{take}/skip")
    assert client.get(take).json()["skipped"] == 1

    finished = client.post(f"{take}/finish").json()  # handed in early: four never reached
    assert (finished["finished"], finished["question"], finished["skipped"]) == (True, None, 1)
    after = client.get(take).json()
    assert (after["attempt"], after["finished"], after["question"]) == (1, True, None)
    assert len(exam_file(config, exam_id)["attempts"]) == 1


def test_a_bad_letter_is_422_and_records_nothing(studio, config):
    client, _, _, engine, _ = studio
    exam_id = create_exam(client, engine)["exam_id"]
    url = f"{BASE}/exams/{exam_id}/take"
    state = client.post(url).json()
    while state["question"]["format"] != "multiple_choice":
        state = client.post(f"{url}/skip").json()

    response = client.post(f"{url}/answer", json={"reply": "Z"})

    assert response.status_code == 422 and "letter" in response.json()["detail"]
    assert client.post(url).json()["question"] == state["question"]  # still the current one


def test_answer_after_finish_is_409(studio, config):
    client, _, _, engine, _ = studio
    exam_id = create_exam(client, engine)["exam_id"]
    url = f"{BASE}/exams/{exam_id}/take"
    for step in ("answer", "skip", "finish"):
        never_taken = client.post(f"{url}/{step}", json={"reply": "A"})
        assert never_taken.status_code == 409 and never_taken.json()["code"] == "no_open_attempt"
    client.post(url)
    client.post(f"{url}/finish")

    for step in ("answer", "skip", "finish"):
        response = client.post(f"{url}/{step}", json={"reply": "A"})
        assert response.status_code == 409, step
        assert response.json()["code"] == "no_open_attempt"
        assert "Attempt 1" in response.json()["detail"]
    assert len(exam_file(config, exam_id)["attempts"]) == 1  # no attempt 2 opened on the side
    assert client.post(url).json()["attempt"] == 2  # taking it again does open one


def test_take_waits_for_a_grade_job(studio, config):
    """The grade job rewrites the file from the copy it loaded: a take step meanwhile is lost."""
    client, _, _, engine, _ = studio
    exam_id = create_exam(client, engine)["exam_id"]
    take_all(client, config, exam_id)
    client.post(f"{BASE}/exams/{exam_id}/take/finish")
    take = f"{BASE}/exams/{exam_id}/take"
    gate = park(engine)
    try:
        grading = client.post(f"{BASE}/exams/{exam_id}/grade").json()
        for url in (take, f"{take}/answer", f"{take}/skip", f"{take}/finish"):
            response = client.post(url, json={"reply": "A"})
            assert response.status_code == 409, url
            assert (response.json()["code"], response.json()["job_id"]) == (
                "job_running",
                grading["id"],
            )
        assert client.get(take).status_code == 200  # reading the attempt is never refused
    finally:
        gate.set()
    engine.drain()
    assert client.post(take).json()["attempt"] == 2


def test_results_of_the_latest_graded_attempt(studio, config):
    client, _, _, engine, _ = studio
    exam_id = create_exam(client, engine)["exam_id"]
    results = f"{BASE}/exams/{exam_id}/results"
    take_all(client, config, exam_id)
    client.post(f"{BASE}/exams/{exam_id}/take/finish")
    assert client.get(results).status_code == 404  # handed in, not graded yet

    run_job(client, engine, client.post(f"{BASE}/exams/{exam_id}/grade"))
    body = client.get(results).json()

    stored = exam_file(config, exam_id)
    (attempt,) = stored["attempts"]
    assert (body["attempt"], body["correct"], body["graded"]) == (1, 4, 6)
    for shown, q in zip(body["questions"], stored["questions"], strict=True):
        assert set(shown) == {
            *RESULT_KEYS,
            "your_answer",
            "skipped",
            "correct",
            "feedback",
            "reference_answer",
        }
        given, grade = attempt["answers"][str(q["index"])], attempt["grades"][str(q["index"])]
        assert (shown["index"], shown["reference_answer"]) == (q["index"], q["answer"])
        assert (shown["your_answer"], shown["correct"]) == (given["answer"], grade["correct"])
        assert shown["correct"] == (q["difficulty"] != "hard")  # take_all gets hard ones wrong
    by_concept = {s["concept_id"]: s for s in body["scores"]}
    for concept_id, change in attempt["mastery"].items():  # from the file, not the job
        score = by_concept[concept_id]
        assert (score["level_before"], score["level_after"]) == (change["before"], change["after"])
    assert sum(s["total"] for s in body["scores"]) == 6

    take = f"{BASE}/exams/{exam_id}/take"
    client.post(take)  # attempt 2: still attempt 1's results while it is taken, and after
    client.post(f"{take}/skip")
    assert client.get(results).json() == body
    client.post(f"{take}/finish")
    assert client.get(results).json()["attempt"] == 1  # attempt 2 isn't graded


def test_results_of_an_attempt_handed_in_early(studio, config):
    client, _, _, engine, _ = studio
    exam_id = create_exam(client, engine)["exam_id"]
    take = f"{BASE}/exams/{exam_id}/take"
    first = client.post(take).json()["question"]
    reply = "B" if first["format"] == "multiple_choice" else "correct: an address"
    client.post(f"{take}/answer", json={"reply": reply})
    client.post(f"{take}/finish")
    run_job(client, engine, client.post(f"{BASE}/exams/{exam_id}/grade"))

    body = client.get(f"{BASE}/exams/{exam_id}/results").json()

    assert (body["correct"], body["graded"]) == (1, 1)
    answered, *rest = sorted(body["questions"], key=lambda q: q["index"] != first["index"])
    assert (answered["skipped"], answered["correct"]) == (False, True)
    assert all((q["skipped"], q["your_answer"], q["correct"]) == (True, None, None) for q in rest)


def test_a_bad_attempt_in_a_file_is_left_out_not_a_500(studio, config, caplog):
    client, _, _, engine, _ = studio
    exam_id = create_exam(client, engine)["exam_id"]
    client.post(f"{BASE}/exams/{exam_id}/take")
    path = config.vault_root / "courses" / COURSE / "exams" / f"{exam_id}.json"
    exam = json.loads(path.read_text())
    exam["attempts"].append({"answers": {}})  # a hand edit: no number, no start time
    path.write_text(json.dumps(exam))

    (listed,) = client.get(f"{BASE}/exams").json()

    assert [a["attempt"] for a in listed["attempts"]] == [1]
    assert "attempt 2 has no number or start time" in caplog.text


def test_the_spec_template(studio):
    client, *_ = studio
    text = client.get(f"{BASE}/exams/template").json()["text"]
    spec = parse_spec(yaml.safe_load(text))
    assert (spec.course, spec.exam, spec.mode) == (COURSE, "Midterm 1", "realistic")
    assert spec.weeks and spec.sources and spec.formats and spec.difficulty


def test_markdown_has_the_answer_key(studio, config):
    client, _, _, engine, _ = studio
    exam_id = create_exam(client, engine)["exam_id"]

    text = client.get(f"{BASE}/exams/{exam_id}/markdown").json()["text"]

    assert text.startswith("# Midterm 1 · CSE220") and "## Answer key" in text
    for q in exam_file(config, exam_id)["questions"]:
        assert q["rubric"] in text and str(q["answer"]) in text


def test_a_bad_spec_is_422_and_queues_nothing(studio):
    client, _, _, engine, _ = studio
    for spec_yaml, says in [
        ("course: [CSE220", "Not valid YAML"),
        ("course: CSE220\nexam: Midterm 1\n", "missing key(s)"),
        (yaml.dump({**SPEC, "course": "CSE221"}), "for CSE221"),
    ]:
        response = client.post(f"{BASE}/exams", json={"spec_yaml": spec_yaml})
        assert response.status_code == 422, spec_yaml
        assert says in response.json()["detail"]
    assert engine.jobs.all(COURSE) == []


def test_exam_create_with_a_session_open(studio):
    client, kp, _, engine, learner = studio
    session = learner.start_session(COURSE)

    refused = client.post(f"{BASE}/exams", json={"spec_yaml": yaml.dump(SPEC)})

    assert refused.status_code == 409 and refused.json()["code"] == "session_open"
    learner.close_session(session.session_id)
    gate = park(engine)
    try:  # a session opens (say, in the CLI) after the route's check, before the job runs
        queued = client.post(f"{BASE}/exams", json={"spec_yaml": yaml.dump(SPEC)})
        assert queued.json()["status"] == "queued"
        late = learner.start_session(COURSE)
    finally:
        gate.set()
    job = run_job(client, engine, queued)
    assert job["status"] == "failed" and late.session_id in job["error"]
    assert kp.queries == []  # it never reached NotebookLM


def test_dotdot_and_missing_exam_ids_are_404(studio):
    client, _, _, engine, _ = studio
    create_exam(client, engine)
    for exam_id in ("%2E%2E", "nope", "%2E%2E%2Fsecret"):
        exam = f"{BASE}/exams/{exam_id}"
        assert client.get(exam).status_code == 404, exam_id
        assert client.get(f"{exam}/markdown").status_code == 404, exam_id
        assert client.post(f"{exam}/take").status_code == 404, exam_id
        assert client.post(f"{exam}/take/answer", json={"reply": "A"}).status_code == 404
        assert client.post(f"{exam}/grade").status_code == 404, exam_id
        assert client.get(f"{exam}/take").status_code == 404, exam_id
        assert client.get(f"{exam}/results").status_code == 404, exam_id
    assert [j["kind"] for j in client.get("/api/jobs").json()] == ["exam_create"]


# -- podcasts ------------------------------------------------------------------------------


def test_podcast_job_records_the_episode_and_serves_its_files(studio, config):
    client, kp, _, engine, _ = studio

    job = run_job(client, engine, client.post(f"{BASE}/podcast", json={"length": "long"}))

    assert job["kind"] == "podcast" and job["status"] == "done", job["error"]
    ((_, (instructions, fmt, length)),) = [c for c in kp.calls if c[0] == "generate_audio"]
    assert (fmt, length) == ("deep-dive", "long")
    episode = job["result"]["episode"]
    assert job["result"]["focus"] == ["Bitwise operators", "Pointers"]
    assert client.get(f"{BASE}/podcasts").json() == [episode]
    audio = client.get(episode["audio_url"])
    assert audio.status_code == 200 and audio.content == b"ID3fake"
    assert audio.headers["content-type"] == "audio/mp4"
    assert client.get(episode["brief_url"]).json() == {"text": instructions}
    folder = config.storage_root / "Fall-2026" / COURSE / "_generated"
    (mp3,) = folder.glob("*-podcast.mp3")
    conn = connect(config.db_path)
    (row,) = PodcastStore(conn).all(COURSE)
    conn.close()
    assert row.id == episode["id"] and row.audio_path == str(mp3)
    assert row.concepts == episode["concepts"] == ["cse220/bitwise-operators", "cse220/pointers"]

    mp3.unlink()  # the row stays; the file it names is gone
    assert client.get(episode["audio_url"]).status_code == 404
    assert client.get(episode["brief_url"]).status_code == 200
    (folder / f"{mp3.stem}.md").unlink()
    assert client.get(episode["brief_url"]).status_code == 404


def test_podcast_for_an_exam_already_created(studio):
    client, kp, _, engine, _ = studio
    create_exam(client, engine)

    job = run_job(client, engine, client.post(f"{BASE}/podcast", json={"exam": "midterm1"}))

    assert job["status"] == "done", job["error"]
    ((_, (instructions, _, _)),) = [c for c in kp.calls if c[0] == "generate_audio"]
    assert "Midterm 1" in instructions


@pytest.mark.parametrize("body", [{"exam": "Final"}, {"format": "opera"}, {"length": "epic"}])
def test_a_bad_podcast_request_is_422_and_queues_nothing(studio, body):
    client, _, _, engine, _ = studio
    assert client.post(f"{BASE}/podcast", json=body).status_code == 422
    assert engine.jobs.all(COURSE) == []


def test_a_podcasts_exam_is_never_read_from_a_path(studio, tmp_path):
    """The CLI's --exam takes a spec file; the API looks in the vault's created exams only."""
    client, _, _, engine, _ = studio
    spec_file = tmp_path / "midterm.yaml"
    spec_file.write_text(yaml.dump(SPEC))  # a valid spec, which find_spec would read

    response = client.post(f"{BASE}/podcast", json={"exam": str(spec_file)})

    assert response.status_code == 422 and "No created CSE220 exam" in response.json()["detail"]
    assert engine.jobs.all(COURSE) == []


def test_missing_podcasts_are_404(studio):
    client, *_ = studio
    assert client.get("/api/podcasts/99/audio").status_code == 404
    assert client.get("/api/podcasts/99/brief").status_code == 404
    assert client.get(f"{BASE}/podcasts").json() == []
