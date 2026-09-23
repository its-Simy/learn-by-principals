import sqlite3
from contextlib import contextmanager

import pytest

from cli import common, doctor
from cli.doctor import Status
from core.memory.db import connect
from core.memory.schema import SCHEMA_VERSION
from core.providers.state import ProviderState


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
    blocker.write_text("")
    blocked = doctor.Config(**{**config.__dict__, "storage_root": blocker / "courses"})
    assert doctor.check_storage(blocked).status is Status.FAIL


def test_tmp_dir(config):
    assert doctor.check_tmp(config).status is Status.OK
    config.tmp_dir.mkdir()
    assert doctor.check_tmp(config).status is Status.OK
    (config.tmp_dir / "leftover").write_text("")
    assert doctor.check_tmp(config).status is Status.FAIL


def test_api_key():
    assert doctor.check_api_key({}).status is Status.OK
    assert doctor.check_api_key({"ANTHROPIC_API_KEY": "sk-x"}).status is Status.FAIL


@pytest.mark.parametrize(
    ("state", "status"),
    [
        (ProviderState.AVAILABLE, Status.OK),
        (ProviderState.AUTH_EXPIRED, Status.FAIL),
        (ProviderState.BROKEN, Status.FAIL),
    ],
)
def test_brightspace(config, monkeypatch, state, status):
    class Lms:
        def health(self):
            return state

    @contextmanager
    def fake_open_lms(config):
        yield Lms()

    monkeypatch.setattr(common, "open_lms", fake_open_lms)
    assert doctor.check_brightspace(config).status is status


def test_run_checks_reports_a_crashing_check_as_failed(config, monkeypatch):
    def boom():
        raise RuntimeError("no driver")

    monkeypatch.setattr(doctor, "checks", lambda config: [("Chromium", boom)])
    assert doctor.run_checks(config) == [
        doctor.Check("Chromium", Status.FAIL, "RuntimeError: no driver")
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
