"""Value lists shared by the code and the database. The DDL itself lives in one frozen file per
migration under ``core/memory/migrations/``, which never import these lists (they may grow)."""

from core.memory.migrations import MIGRATIONS, SCHEMA_VERSION

__all__ = [
    "BENCHMARK_METRICS",
    "CHALLENGE_STATUSES",
    "CONCEPT_STATUSES",
    "EVIDENCE_STRENGTHS",
    "EVIDENCE_TYPES",
    "MASTERY_CHANGERS",
    "MIGRATIONS",
    "SCHEMA_VERSION",
    "SYNC_STATES",
]

SYNC_STATES = ("pending", "synced", "stale", "failed", "link", "deferred")
EVIDENCE_TYPES = ("explained", "applied", "transferred", "failed", "misconception")
EVIDENCE_STRENGTHS = ("weak", "moderate", "strong")
MASTERY_CHANGERS = ("analyzer", "manual", "challenger")  # "challenger" since v9 (BL-040)
CHALLENGE_STATUSES = ("pending", "asked", "answered", "resolved")
CONCEPT_STATUSES = ("active", "retired")  # since v11 (BL-040)
BENCHMARK_METRICS = (
    "accuracy",
    "groundedness",
    "format_compliance",
    "latency_ms",
    "learner_rating",
)
