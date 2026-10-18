"""``brightlearn courses add``: the code is optional and derived from the name when left out."""

from typer.testing import CliRunner

from cli.app import app
from core.config import load_config
from core.memory.db import Courses, connect

runner = CliRunner()


def test_add_derives_the_code_from_the_name(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BRIGHTLEARN_TERM", "Fall-2026")
    result = runner.invoke(app, ["courses", "add", "--name", "Linear Algebra"])
    assert result.exit_code == 0, result.output
    assert "Added LINEAR-ALGEBRA (Linear Algebra)" in result.output
    assert "Fall-2026/LINEAR-ALGEBRA" in result.output.replace("\n", "")
    again = runner.invoke(app, ["courses", "add", "--name", "Linear Algebra"])
    assert "Added LINEAR-ALGEBRA-2" in again.output
    explicit = runner.invoke(app, ["courses", "add", "math201", "--name", "Linear Algebra"])
    assert "Added MATH201" in explicit.output
    conn = connect(load_config().db_path)
    try:
        codes = [c.course for c in Courses(conn).all()]
        assert codes == ["LINEAR-ALGEBRA", "LINEAR-ALGEBRA-2", "MATH201"]
    finally:
        conn.close()


def test_add_still_needs_a_name(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "home"))
    assert runner.invoke(app, ["courses", "add"]).exit_code == 2
