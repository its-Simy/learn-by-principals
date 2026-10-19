"""``brightlearn setup``: the checks beyond doctor, and the command's login behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.app import app
from cli.maintain import NO_AUTO_RUN
from core import setup as core_setup
from core.config import Config, default_config_toml, ensure_home, load_config, write_default_config
from core.doctor import Check, Status

runner = CliRunner()


def test_default_config_is_written_once_and_never_overwritten(config: Config):
    ensure_home(config)
    assert write_default_config(config) is True
    text = config.config_path.read_text(encoding="utf-8")
    assert text == default_config_toml()
    # Every line is a comment, so the file changes nothing.
    assert all(line.startswith("#") for line in text.splitlines())
    assert load_config({"BRIGHTLEARN_HOME": str(config.home)}).routing["teaching"] == (
        "claude",
        "codex",
    )
    config.config_path.write_text('[routing]\nteaching = ["codex"]\n', encoding="utf-8")
    assert write_default_config(config) is False
    assert "codex" in config.config_path.read_text(encoding="utf-8")


def test_ensure_home_creates_the_staging_dir(config: Config):
    ensure_home(config)
    assert config.tmp_dir.is_dir()


def test_web_build_check(tmp_path: Path):
    assert core_setup.check_web_build(tmp_path).status is Status.FAIL
    (tmp_path / "index.html").write_text("<html/>", encoding="utf-8")
    assert core_setup.check_web_build(tmp_path).status is Status.OK


@pytest.mark.parametrize("platform", ["macos", "windows", "linux"])
@pytest.mark.parametrize("name", ["claude", "codex"])
def test_every_cli_has_an_install_hint_per_platform(name, platform):
    assert core_setup.install_hint(name, platform)
    assert core_setup.LOGIN_HINTS[name]


def test_default_browser_is_edge_on_a_windows_machine_without_chrome(tmp_path, monkeypatch):
    assert core_setup.default_browser("macos") == "chrome"
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert core_setup.default_browser("windows") == "msedge"
    exe = tmp_path / "Google" / "Chrome" / "Application" / "chrome.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert core_setup.default_browser("windows") == "chrome"


class Shimmed:
    binary = "codex"

    def __init__(self, exe: str | None) -> None:
        self.exe = exe

    def executable(self):
        return self.exe

    def version(self):
        return "codex 1.0" if self.exe else None

    def health(self):
        return "AVAILABLE"


def test_a_cmd_shim_is_a_warning_with_the_native_hint():
    assert core_setup.check_model_cli_install("Codex", Shimmed(None)).status is Status.WARN
    native = core_setup.check_model_cli_install("Codex", Shimmed("/usr/bin/codex"))
    assert native.status is Status.OK
    shim = core_setup.check_model_cli_install("Codex", Shimmed(r"C:\npm\codex.CMD"))
    assert shim.status is Status.WARN and "cmd.exe" in shim.detail


def test_blocking_is_the_build_and_the_login():
    ok = Check("Web app", Status.OK, "")
    assert not core_setup.blocking([ok, Check("Codex", Status.FAIL, "")])
    assert core_setup.blocking([ok, Check("NotebookLM", Status.FAIL, "")])
    assert not core_setup.blocking([ok, Check("NotebookLM", Status.WARN, "skipped")])


def test_setup_never_runs_maintenance():
    assert "setup" in NO_AUTO_RUN


# -- the command ----------------------------------------------------------------------------


@pytest.fixture
def setup_env(tmp_path, monkeypatch):
    """A built web app, a NotebookLM library whose login we script, and no model CLIs."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html/>", encoding="utf-8")
    monkeypatch.setattr("api.static.DIST", dist)
    state = {"logged_in": False, "logins": []}
    nlm = "cli.setup.gemini_notebook"
    monkeypatch.setattr(f"{nlm}.library_installed", lambda: True)
    monkeypatch.setattr(
        f"{nlm}.auth_check",
        lambda config: (True, "auth check ok") if state["logged_in"] else (False, "no login"),
    )

    def login(config, account, browser=None):
        state["logins"].append((account, browser))
        state["logged_in"] = True
        return 0

    monkeypatch.setattr(f"{nlm}.login", login)
    monkeypatch.setattr("cli.setup.wiring.open_model", lambda name, config: Shimmed(None))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return state, dist


def test_setup_logs_in_with_the_given_account(setup_env):
    state, _ = setup_env
    result = runner.invoke(app, ["setup", "--account", "me@example.com", "--browser", "chrome"])
    assert result.exit_code == 0, result.output
    assert state["logins"] == [("me@example.com", "chrome")]
    assert "Ready." in result.output
    assert "Claude Code" in result.output and "install:" in result.output
    # A second run finds the login and asks for nothing.
    again = runner.invoke(app, ["setup", "--yes"])
    assert again.exit_code == 0 and state["logins"] == [("me@example.com", "chrome")]


def test_setup_skips_the_login_when_told(setup_env):
    state, _ = setup_env
    result = runner.invoke(app, ["setup", "--skip-login"])
    assert result.exit_code == 0, result.output
    assert state["logins"] == [] and "skipped" in result.output


def test_setup_with_yes_and_no_account_warns_instead_of_prompting(setup_env):
    state, _ = setup_env
    result = runner.invoke(app, ["setup", "--yes"])
    assert result.exit_code == 0, result.output
    assert state["logins"] == [] and "--account" in result.output


def test_setup_prompts_for_the_account(setup_env):
    state, _ = setup_env
    result = runner.invoke(app, ["setup"], input="me@example.com\n")
    assert result.exit_code == 0, result.output
    assert state["logins"] == [("me@example.com", "chrome")]


def test_setup_fails_without_the_web_build(setup_env):
    _, dist = setup_env
    (dist / "index.html").unlink()
    result = runner.invoke(app, ["setup", "--skip-login"])
    assert result.exit_code == 1
    assert "pnpm --dir web" in result.output and "Not ready" in result.output


def test_setup_writes_config_toml_and_the_home(setup_env, monkeypatch):
    result = runner.invoke(app, ["setup", "--skip-login"])
    assert result.exit_code == 0, result.output
    config = load_config()
    assert config.config_path.exists() and config.tmp_dir.is_dir()
