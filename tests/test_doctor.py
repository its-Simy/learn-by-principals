import os
import sqlite3

import pytest

from core import doctor
from core.doctor import Status
from core.memory.db import connect
from core.memory.schema import SCHEMA_VERSION


@pytest.mark.skipif(os.name == "nt", reason="Windows folders carry ACLs, not mode bits")
def test_config_warns_when_home_is_readable_by_others(config):
    config.home.mkdir(mode=0o755)
    config.home.chmod(0o755)
    assert doctor.check_config(config).status is Status.WARN
    config.home.chmod(0o700)
    assert doctor.check_config(config).status is Status.OK


def test_db_schema(config):
    assert doctor.check_db(config).status is Status.WARN  # not created yet
    connect(config.db_path).close()
    assert doctor.check_db(config) == doctor.Check("DB schema", Status.OK, f"v{SCHEMA_VERSION}")

    conn = sqlite3.connect(config.db_path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.close()
    assert doctor.check_db(config).status is Status.FAIL


def test_db_check_does_not_create_the_database(config):
    doctor.check_db(config)
    assert not config.db_path.exists()


def test_storage_root(config, tmp_path):
    assert doctor.check_storage(config).status is Status.OK
    blocker = tmp_path / "blocker"
    blocker.write_text("", encoding="utf-8")
    blocked = doctor.Config(**{**config.__dict__, "storage_root": blocker / "courses"})
    assert doctor.check_storage(blocked).status is Status.FAIL


def test_tmp_dir(config):
    assert doctor.check_tmp(config).status is Status.OK
    config.tmp_dir.mkdir()
    assert doctor.check_tmp(config).status is Status.OK
    (config.tmp_dir / "leftover").write_text("", encoding="utf-8")
    assert doctor.check_tmp(config).status is Status.FAIL


def test_api_key():
    assert doctor.check_api_key({}).status is Status.OK
    assert doctor.check_api_key({"ANTHROPIC_API_KEY": "sk-x"}).status is Status.FAIL


def test_run_checks_reports_a_crashing_check_as_failed(config, monkeypatch):
    def boom():
        raise RuntimeError("no driver")

    monkeypatch.setattr(doctor, "checks", lambda config: [("NotebookLM", boom)])
    assert doctor.run_checks(config) == [
        doctor.Check("NotebookLM", Status.FAIL, "RuntimeError: no driver")
    ]


def test_checks_cover_only_local_state_and_the_providers(config):
    """Files are uploaded by hand: no browser or course-site login to check (BL-042)."""
    assert [name for name, _ in doctor.checks(config)] == [
        "Config",
        "DB schema",
        "Storage root",
        "Temp dir",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "NotebookLM",
        "Claude Code",
        "Codex",
    ]


def test_unbuilt_providers_are_not_configured(config, monkeypatch):
    names = {name for name, _ in doctor.checks(config)}
    assert {"NotebookLM", "Claude Code", "Codex"} <= names
    assert doctor.not_configured("Codex", "BL-023").status is Status.OFF


def test_notebooklm_not_installed_warns(config, monkeypatch):
    monkeypatch.setattr(doctor.gemini_notebook, "library_installed", lambda: False)
    assert doctor.check_notebooklm(config).status is Status.WARN


@pytest.mark.parametrize(("ok", "status"), [(True, Status.OK), (False, Status.FAIL)])
def test_notebooklm_auth_check(config, monkeypatch, ok, status):
    monkeypatch.setattr(doctor.gemini_notebook, "library_installed", lambda: True)
    monkeypatch.setattr(doctor.gemini_notebook, "auth_check", lambda config: (ok, "detail"))
    assert doctor.check_notebooklm(config).status is status


def test_model_cli_check_reports_version_or_missing(tmp_path, monkeypatch):
    from core.providers.models.claude_code import ClaudeCodeProvider

    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    provider = ClaudeCodeProvider(tmp_path / "scratch")
    assert doctor.check_model_cli("Claude Code", provider).status is Status.WARN
    monkeypatch.setattr(provider, "version", lambda: "2.1.280 (Claude Code)")
    assert doctor.check_model_cli("Claude Code", provider).status is Status.OK
