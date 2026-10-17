from pathlib import Path

import pytest

from core.config import Config


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch) -> None:
    """No test ever reads or writes the real ~/.brightlearn (tests may override these)."""
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "isolated-home"))
    monkeypatch.setenv("BRIGHTLEARN_VAULT", str(tmp_path / "isolated-vault"))


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
