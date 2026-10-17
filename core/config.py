"""Runtime configuration. Secrets live under ``home`` (``~/.brightlearn/``) and nowhere else."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

DEFAULT_TMP_DIR = Path("/tmp/brightlearn")

# v0 routing: provider order per purpose, overridable in config.toml [routing]. Benchmarks-driven
# routing replaces this in Phase 10 (principle 8; see the decision log in CLAUDE.md).
DEFAULT_ROUTING: dict[str, tuple[str, ...]] = {
    "teaching": ("claude", "codex"),
    "analysis": ("codex", "claude"),
    # Housekeeping can fall all the way to the local model; classify tries it first (BL-036).
    "housekeeping": ("claude", "codex", "ollama"),
    "classify": ("ollama", "claude", "codex"),
}
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2:3b"


class ConfigError(Exception):
    pass


def default_term(today: date | None = None) -> str:
    """The default term for new courses, guessed from the calendar, e.g. ``Fall-2026``."""
    today = today or date.today()
    if today.month <= 5:
        season = "Spring"
    elif today.month <= 7:
        season = "Summer"
    else:
        season = "Fall"
    return f"{season}-{today.year}"


@dataclass(frozen=True)
class Config:
    home: Path
    term: str
    storage_root: Path
    tmp_dir: Path
    db_path: Path
    vault_root: Path
    nlm_min_interval_s: float = 1.5
    nlm_source_cap: int = 50
    nlm_artifact_timeout_s: float = 1200.0
    model_timeout_s: float = 300.0
    retention_half_life_days: float = 21.0
    ollama_url: str = DEFAULT_OLLAMA_URL
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    routing: dict[str, tuple[str, ...]] = field(default_factory=lambda: dict(DEFAULT_ROUTING))

    @property
    def config_path(self) -> Path:
        return self.home / "config.toml"

    @property
    def notebooklm_home(self) -> Path:
        """``NOTEBOOKLM_HOME`` for notebooklm-py: its master token and cookies live here."""
        return self.home / "notebooklm"

    @property
    def notebooklm_storage_path(self) -> Path:
        return self.notebooklm_home / "profiles" / "default" / "storage_state.json"


def load_config(env: Mapping[str, str] | None = None, term: str | None = None) -> Config:
    env = os.environ if env is None else env
    home = Path(env.get("BRIGHTLEARN_HOME", Path.home() / ".brightlearn")).expanduser()
    return Config(
        home=home,
        term=term or env.get("BRIGHTLEARN_TERM") or default_term(),
        storage_root=Path(env.get("BRIGHTLEARN_STORAGE_ROOT", home / "courses")).expanduser(),
        tmp_dir=Path(env.get("BRIGHTLEARN_TMP_DIR", DEFAULT_TMP_DIR)).expanduser(),
        db_path=Path(env.get("BRIGHTLEARN_DB", home / "brightlearn.db")).expanduser(),
        vault_root=Path(env.get("BRIGHTLEARN_VAULT", home / "vault")).expanduser(),
        nlm_min_interval_s=float(env.get("BRIGHTLEARN_NLM_MIN_INTERVAL_S", 1.5)),
        nlm_source_cap=int(env.get("BRIGHTLEARN_NLM_SOURCE_CAP", 50)),
        nlm_artifact_timeout_s=float(env.get("BRIGHTLEARN_NLM_ARTIFACT_TIMEOUT_S", 1200)),
        model_timeout_s=float(env.get("BRIGHTLEARN_MODEL_TIMEOUT_S", 300)),
        retention_half_life_days=float(env.get("BRIGHTLEARN_RETENTION_HALF_LIFE_DAYS", 21)),
        ollama_url=env.get("BRIGHTLEARN_OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/"),
        ollama_model=env.get("BRIGHTLEARN_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
        routing=load_routing(home / "config.toml"),
    )


def load_routing(path: Path) -> dict[str, tuple[str, ...]]:
    """``[routing]`` from config.toml over the defaults, e.g. ``teaching = ["claude", "codex"]``."""
    routing = dict(DEFAULT_ROUTING)
    if not path.exists():
        return routing
    try:
        table = tomllib.loads(path.read_text()).get("routing", {})
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    for purpose, order in table.items():
        if not (isinstance(order, list) and order and all(isinstance(n, str) for n in order)):
            raise ConfigError(f"{path}: [routing] {purpose} must be a non-empty list of names")
        routing[purpose] = tuple(order)
    return routing


def ensure_home(config: Config) -> None:
    """Create the secrets directory with owner-only permissions."""
    config.home.mkdir(mode=0o700, parents=True, exist_ok=True)
    config.home.chmod(0o700)
