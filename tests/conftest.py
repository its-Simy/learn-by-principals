from pathlib import Path

import pytest

from core.config import Config


@pytest.fixture
def config(tmp_path: Path) -> Config:
    home = tmp_path / "home"
    return Config(
        home=home,
        brightspace_base_url="https://mycourses.example.edu",
        term="Fall-2026",
        storage_root=home / "courses",
        tmp_dir=tmp_path / "tmp",
        db_path=home / "brightlearn.db",
        vault_root=tmp_path / "memory",
    )
