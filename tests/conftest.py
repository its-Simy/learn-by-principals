from pathlib import Path

import pytest

from core.config import Config


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch) -> None:
    """No test ever reads or writes the real ~/.brightlearn (tests may override these)."""
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "isolated-home"))
    monkeypatch.setenv("BRIGHTLEARN_VAULT", str(tmp_path / "isolated-vault"))
    monkeypatch.setenv("BRIGHTLEARN_TMP_DIR", str(tmp_path / "isolated-tmp"))


@pytest.fixture
def config(tmp_path: Path) -> Config:
    home = tmp_path / "home"
    return Config(
        home=home,
        term="Fall-2026",
        storage_root=home / "courses",
        tmp_dir=tmp_path / "tmp",
        db_path=home / "brightlearn.db",
        vault_root=tmp_path / "memory",
    )


@pytest.fixture
def api(config: Config, tmp_path: Path):
    """The web API on fakes: ``(client, knowledge, models, engine)``.

    Each worker thread opens its own connection, as the real ``open_resources`` does, and both
    share one ``FakeKnowledge`` and the two ``FakeModel``s, so a test can inspect what they got.
    """
    from fastapi.testclient import TestClient

    from api.app import create_app
    from api.engine import Engine, Resources
    from core.memory.db import connect
    from tests.fakes.fake_knowledge import FakeKnowledge
    from tests.fakes.fake_models import FakeModel

    kp = FakeKnowledge(out_dir=tmp_path / "nlm-out")
    models = {"claude": FakeModel("claude"), "codex": FakeModel("codex")}

    def fake_resources(cfg: Config) -> Resources:
        return Resources(cfg, connect(cfg.db_path), kp, dict(models))

    engine = Engine(config, open_resources=fake_resources)
    # The app only answers to 127.0.0.1 and localhost, not TestClient's default "testserver".
    with TestClient(create_app(config, engine), base_url="http://127.0.0.1:8765") as client:
        yield client, kp, models, engine
