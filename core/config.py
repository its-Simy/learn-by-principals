"""Runtime configuration. Secrets live under ``home`` (``~/.brightlearn/``) and nowhere else."""

from __future__ import annotations

import logging
import os
import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

# Upload staging. /tmp on macOS and Linux as always; Windows has no /tmp, so its temp folder.
DEFAULT_TMP_DIR = (
    Path(tempfile.gettempdir()) / "brightlearn" if os.name == "nt" else Path("/tmp/brightlearn")
)

# v0 routing: provider order per purpose, overridable in config.toml [routing]. Benchmarks-driven
# routing replaces this in Phase 10 (principle 8; see the decision log in CLAUDE.md).
DEFAULT_ROUTING: dict[str, tuple[str, ...]] = {
    "teaching": ("claude", "codex"),
    "analysis": ("codex", "claude"),
    "housekeeping": ("claude", "codex"),
    "classify": ("claude", "codex"),
}
# The model providers this build ships (core/wiring.py builds them). A name in config.toml that
# isn't here is dropped with a warning, so a stale entry (e.g. the removed "ollama") can't make
# every job fail at start-up.
KNOWN_PROVIDERS = frozenset({"claude", "codex"})


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
        routing=load_routing(home / "config.toml"),
    )


def load_routing(path: Path) -> dict[str, tuple[str, ...]]:
    """``[routing]`` from config.toml over the defaults, e.g. ``teaching = ["claude", "codex"]``."""
    routing = dict(DEFAULT_ROUTING)
    if not path.exists():
        return routing
    try:
        with path.open("rb") as f:  # TOML is UTF-8 by definition; tomllib decodes it itself
            table = tomllib.load(f).get("routing", {})
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    for purpose, order in table.items():
        if not (isinstance(order, list) and order and all(isinstance(n, str) for n in order)):
            raise ConfigError(f"{path}: [routing] {purpose} must be a non-empty list of names")
        unknown = [n for n in order if n not in KNOWN_PROVIDERS]
        if unknown:
            log.warning(
                "%s: [routing] %s names unknown provider(s) %s; skipped", path, purpose, unknown
            )
        kept = tuple(n for n in order if n in KNOWN_PROVIDERS)
        if not kept:
            raise ConfigError(
                f"{path}: [routing] {purpose} names no known provider ({sorted(KNOWN_PROVIDERS)})"
            )
        routing[purpose] = kept
    return routing


def ensure_home(config: Config) -> None:
    """Create the secrets directory with owner-only permissions, and the upload staging dir."""
    config.home.mkdir(mode=0o700, parents=True, exist_ok=True)
    config.home.chmod(0o700)
    config.tmp_dir.mkdir(parents=True, exist_ok=True)


def default_config_toml() -> str:
    """A ``config.toml`` that changes nothing: every setting commented out, with its default."""
    lines = [
        "# BrightLearn settings (optional). A missing key keeps the default shown here.",
        "#",
        "# [routing] orders the model providers per purpose (teaching, analysis, housekeeping,",
        "# classify) or per task type. The first usable provider is tried; the next is the one",
        f"# fallback. Providers in this build: {', '.join(sorted(KNOWN_PROVIDERS))}.",
        "#",
        "# [routing]",
    ]
    for purpose, order in DEFAULT_ROUTING.items():
        names = ", ".join(f'"{n}"' for n in order)
        lines.append(f"# {purpose} = [{names}]")
    return "\n".join(lines) + "\n"


def write_default_config(config: Config) -> bool:
    """Write the commented default ``config.toml`` once; an existing file is never touched."""
    if config.config_path.exists():
        return False
    config.config_path.write_text(default_config_toml(), encoding="utf-8")
    return True
