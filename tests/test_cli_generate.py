import json
from contextlib import contextmanager

import pytest
from typer.testing import CliRunner

from cli.app import app
from core import wiring
from core.config import load_config
from core.memory.db import Courses, connect
from tests.fakes.fake_knowledge import FakeKnowledge

runner = CliRunner()


@pytest.fixture
def kp(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BRIGHTLEARN_TERM", "Spring-2027")  # the course row's term wins
    conn = connect(load_config().db_path)
    Courses(conn).add("CSE220", "Systems Fundamentals", "Fall-2026")
    conn.close()
    kp = FakeKnowledge(out_dir=tmp_path / "downloads")

    @contextmanager
    def fake_open_knowledge(config, conn):
        yield kp

    monkeypatch.setattr(wiring, "open_knowledge", fake_open_knowledge)
    return kp


def generated(tmp_path):
    folder = tmp_path / "home/courses/Fall-2026/CSE220/_generated"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def test_quiz_is_saved_as_json(kp, tmp_path):
    result = runner.invoke(app, ["generate", "quiz", "--course", "CSE220"])
    assert result.exit_code == 0, result.output
    (name,) = generated(tmp_path)
    assert name.endswith("-quiz.json")
    saved = json.loads(
        (tmp_path / "home/courses/Fall-2026/CSE220/_generated" / name).read_text(encoding="utf-8")
    )
    assert saved == kp.quiz


def test_audio_uses_prompt_file_format_and_length(kp, tmp_path):
    prompt = tmp_path / "focus.md"
    prompt.write_text("Cover only grading policy.", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "generate",
            "audio",
            "--course",
            "cse220",
            "--prompt-file",
            str(prompt),
            "--format",
            "brief",
            "--length",
            "short",
        ],
    )
    assert result.exit_code == 0, result.output
    assert kp.calls[-1] == ("generate_audio", ("Cover only grading policy.", "brief", "short"))
    (name,) = generated(tmp_path)
    assert name.endswith("-audio.mp3")  # the fake's extension; real downloads are .m4a
    assert list((tmp_path / "downloads").iterdir()) == []


def test_flashcards_json_and_report_markdown(kp, tmp_path):
    assert runner.invoke(app, ["generate", "flashcards", "--course", "CSE220"]).exit_code == 0
    assert runner.invoke(app, ["generate", "report", "--course", "CSE220"]).exit_code == 0
    names = generated(tmp_path)
    assert any(n.endswith("-flashcards.json") for n in names)
    assert any(n.endswith("-report.md") for n in names)


def test_report_prompt_file_becomes_the_custom_prompt(kp, tmp_path):
    prompt = tmp_path / "p.md"
    prompt.write_text("Summarise week 3.", encoding="utf-8")
    runner.invoke(app, ["generate", "report", "--course", "CSE220", "--prompt-file", str(prompt)])
    assert kp.calls[-1] == ("generate", ("report", {"prompt": "Summarise week 3."}))


def test_out_overrides_destination(kp, tmp_path):
    out = tmp_path / "elsewhere" / "q.json"
    result = runner.invoke(app, ["generate", "quiz", "--course", "CSE220", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text(encoding="utf-8")) == kp.quiz
    assert generated(tmp_path) == []


def test_unknown_kind_is_rejected(kp):
    assert runner.invoke(app, ["generate", "podcast", "--course", "CSE220"]).exit_code == 2


def test_unknown_course_is_rejected_before_notebooklm(kp):
    assert runner.invoke(app, ["generate", "quiz", "--course", "CSE999"]).exit_code == 2
    assert kp.calls == []
