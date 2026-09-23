from datetime import date
from pathlib import Path

from core.config import default_term, load_config


def test_default_term_follows_calendar():
    assert default_term(date(2026, 9, 23)) == "Fall-2026"
    assert default_term(date(2027, 2, 1)) == "Spring-2027"
    assert default_term(date(2027, 6, 15)) == "Summer-2027"


def test_env_overrides(tmp_path):
    config = load_config(
        {"BRIGHTLEARN_HOME": str(tmp_path), "BRIGHTLEARN_TERM": "Fall-2026"}, term=None
    )
    assert config.home == tmp_path
    assert config.term == "Fall-2026"
    assert config.db_path == tmp_path / "brightlearn.db"
    assert config.storage_state_path == tmp_path / "storage_state.json"
    assert config.tmp_dir == Path("/tmp/brightlearn")
    assert config.storage_root == tmp_path / "courses"


def test_secrets_live_under_home(tmp_path):
    config = load_config({"BRIGHTLEARN_HOME": str(tmp_path)})
    for secret in (
        config.browser_profile_dir,
        config.storage_state_path,
    ):
        assert tmp_path in secret.parents


def test_vault_lives_under_home_not_the_repo(tmp_path):
    config = load_config({"BRIGHTLEARN_HOME": str(tmp_path)})
    assert config.vault_root == tmp_path / "vault"
    assert Path(__file__).resolve().parents[1] not in config.vault_root.parents


def test_routing_defaults_and_config_toml(tmp_path):
    assert load_config({"BRIGHTLEARN_HOME": str(tmp_path)}).routing == {
        "teaching": ("claude", "codex"),
        "analysis": ("codex", "claude"),
        "housekeeping": ("claude", "codex", "ollama"),
        "classify": ("ollama", "claude", "codex"),
    }
    (tmp_path / "config.toml").write_text('[routing]\nteaching = ["codex", "claude"]\n')
    routing = load_config({"BRIGHTLEARN_HOME": str(tmp_path)}).routing
    assert routing["teaching"] == ("codex", "claude")
    assert routing["analysis"] == ("codex", "claude")


def test_bad_routing_is_refused(tmp_path):
    import pytest

    from core.config import ConfigError

    (tmp_path / "config.toml").write_text('[routing]\nteaching = "claude"\n')
    with pytest.raises(ConfigError):
        load_config({"BRIGHTLEARN_HOME": str(tmp_path)})
