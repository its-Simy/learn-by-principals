"""Runtime configuration. Secrets live under ``home`` (``~/.brightlearn/``) and nowhere else."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DEFAULT_BASE_URL = "https://mycourses.stonybrook.edu"
DEFAULT_TMP_DIR = Path("/tmp/brightlearn")


def default_term(today: date | None = None) -> str:
    """Best-guess term label from the calendar, e.g. ``2026-Fall``.

    Placeholder until the term can be read from Brightspace (see questions.md).
    """
    today = today or date.today()
    if today.month <= 5:
        season = "Spring"
    elif today.month <= 7:
        season = "Summer"
    else:
        season = "Fall"
    return f"{today.year}-{season}"


@dataclass(frozen=True)
class Config:
    home: Path
    brightspace_base_url: str
    term: str
    storage_root: Path
    tmp_dir: Path
    db_path: Path
    login_timeout_s: int = 600

    @property
    def browser_profile_dir(self) -> Path:
        return self.home / "browser-profile"

    @property
    def storage_state_path(self) -> Path:
        return self.home / "storage_state.json"


def load_config(env: Mapping[str, str] | None = None, term: str | None = None) -> Config:
    env = os.environ if env is None else env
    home = Path(env.get("BRIGHTLEARN_HOME", Path.home() / ".brightlearn")).expanduser()
    return Config(
        home=home,
        brightspace_base_url=env.get("BRIGHTLEARN_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        term=term or env.get("BRIGHTLEARN_TERM") or default_term(),
        storage_root=Path(env.get("BRIGHTLEARN_STORAGE_ROOT", home / "courses")).expanduser(),
        tmp_dir=Path(env.get("BRIGHTLEARN_TMP_DIR", DEFAULT_TMP_DIR)).expanduser(),
        db_path=Path(env.get("BRIGHTLEARN_DB", home / "brightlearn.db")).expanduser(),
    )


def ensure_home(config: Config) -> None:
    """Create the secrets directory with owner-only permissions."""
    config.home.mkdir(mode=0o700, parents=True, exist_ok=True)
    config.home.chmod(0o700)
