from contextlib import contextmanager

import pytest
from typer.testing import CliRunner

from cli import common
from cli.app import app
from core.providers.lms.base import Course, Resource
from core.providers.state import ProviderState
from tests.fakes.fake_knowledge import FakeKnowledge
from tests.fakes.fake_models import FakeModel
from tests.fakes.lms import FakeLMS

runner = CliRunner()
CSE220 = Course(100001, "CSE220", "CSE 220")
AMS161 = Course(100002, "AMS161", "AMS 161")


@pytest.fixture
def lms(tmp_path, monkeypatch) -> FakeLMS:
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BRIGHTLEARN_TMP_DIR", str(tmp_path / "tmp"))
    monkeypatch.setenv("BRIGHTLEARN_TERM", "Fall-2026")
    lms = FakeLMS([CSE220, AMS161])
    lms.add(Resource(100001, 1, "Week 1", "Lecture 1", "File", None, "t1"), "lec1.pdf", b"one")
    lms.add(Resource(100001, 2, "Week 1", "Zoom", "Link", "https://z", "t1"))
    lms.add(Resource(100002, 3, "Week 1", "Syllabus", "File", None, "t1"), "syl.pdf", b"s")

    @contextmanager
    def fake_open_lms(config):
        yield lms

    monkeypatch.setattr(common, "open_lms", fake_open_lms)
    return lms


@pytest.fixture(autouse=True)
def ollama(monkeypatch) -> FakeModel:
    """A local model that's off unless a test turns it on; sync never reaches a real one."""
    model = FakeModel("ollama", "labs")
    model.task_types = frozenset({"classify", "extract_metadata", "summarize"})
    model.state = ProviderState.DISABLED
    monkeypatch.setattr(common, "open_model", lambda name, config: model)
    return model


@pytest.fixture(autouse=True)
def knowledge(monkeypatch) -> FakeKnowledge:
    kp = FakeKnowledge()

    @contextmanager
    def fake_open_knowledge(config, conn):
        yield kp

    monkeypatch.setattr(common, "open_knowledge", fake_open_knowledge)
    return kp


def test_sync_one_course_then_all_skipped(lms, tmp_path):
    first = runner.invoke(app, ["sync", "--course", "CSE220"])
    assert first.exit_code == 0, first.output
    assert (tmp_path / "home/courses/Fall-2026/CSE220/lectures/lec1.pdf").read_bytes() == b"one"

    second = runner.invoke(app, ["sync", "--course", "CSE220"])
    assert second.exit_code == 0
    assert "CSE220 │ 0   │ 0       │ 1       │ 1     │ 0" in second.output


def test_sync_all(lms, tmp_path):
    result = runner.invoke(app, ["sync", "--all"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "home/courses/Fall-2026/AMS161/syllabus/syl.pdf").exists()


def test_dry_run_writes_no_files(lms, tmp_path):
    result = runner.invoke(app, ["sync", "--all", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "dry run" in result.output
    assert not (tmp_path / "home/courses").exists()


def test_failures_are_listed_and_exit_nonzero(lms):
    lms.fail_topics.add(1)
    result = runner.invoke(app, ["sync", "--course", "CSE220"])
    assert result.exit_code == 1
    assert "CSE220: topic 1 'Lecture 1': connection reset" in result.output


@pytest.mark.parametrize("args", [[], ["--course", "CSE220", "--all"]])
def test_exactly_one_of_course_or_all(lms, args):
    assert runner.invoke(app, ["sync", *args]).exit_code == 2


def test_unknown_course(lms):
    result = runner.invoke(app, ["sync", "--course", "CSE999"])
    assert result.exit_code == 2


def test_sync_links_new_files_to_notebooklm(lms, knowledge):
    result = runner.invoke(app, ["sync", "--course", "CSE220"])
    assert result.exit_code == 0, result.output
    assert [c[1].name for c in knowledge.calls if c[0] == "add_file"] == ["lec1.pdf"]
    assert "NotebookLM" in result.output


def test_no_link_and_dry_run_skip_notebooklm(lms, knowledge):
    assert runner.invoke(app, ["sync", "--course", "CSE220", "--no-link"]).exit_code == 0
    assert runner.invoke(app, ["sync", "--course", "CSE220", "--dry-run"]).exit_code == 0
    assert knowledge.calls == []


def test_link_failures_exit_nonzero(lms, knowledge, monkeypatch):
    def boom(notebook_id, path):
        raise RuntimeError("upload refused")

    monkeypatch.setattr(knowledge, "add_file", boom)
    result = runner.invoke(app, ["sync", "--course", "CSE220"])
    assert result.exit_code == 1
    assert "upload refused" in result.output


@pytest.mark.parametrize(
    "state, bucket", [(ProviderState.AVAILABLE, "labs"), (ProviderState.DISABLED, "other")]
)
def test_ambiguous_titles_go_to_the_local_model_only_when_available(
    lms, ollama, tmp_path, state, bucket
):
    lms.add(Resource(100001, 9, "Week 1", "dweight2", "File", None, "t1"), "dweight2", b"?")
    ollama.state = state

    result = runner.invoke(app, ["sync", "--course", "CSE220", "--no-link"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / f"home/courses/Fall-2026/CSE220/{bucket}/dweight2").exists()
    asked = [t for t in ollama.tasks if t.task_type == "classify"]
    assert len(asked) == (1 if state is ProviderState.AVAILABLE else 0)  # clear titles never ask
