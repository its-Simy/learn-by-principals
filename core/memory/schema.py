"""SQLite DDL, applied as numbered migrations tracked in ``PRAGMA user_version``.

v1: the sync manifest, ledger and notebook cache. v2: learner memory. v3: the mastery audit
trail. v4: Challenger probes. v5: concept weeks. v6: podcast episodes. v7: benchmarks and
provider health (router v1). Later tables land with their ticket as new migrations.
"""

SYNC_STATES = ("pending", "synced", "stale", "failed", "link", "deferred")

RESOURCES = f"""
CREATE TABLE resources (
    course             TEXT NOT NULL,
    org_unit_id        INTEGER NOT NULL,
    topic_id           INTEGER PRIMARY KEY,
    module_path        TEXT NOT NULL,
    title              TEXT NOT NULL,
    type_identifier    TEXT NOT NULL,
    url                TEXT,
    filename           TEXT,
    size               INTEGER,
    last_modified      TEXT,
    hash               TEXT,
    local_path         TEXT,
    bucket             TEXT,
    notebook_id        TEXT,
    notebook_source_id TEXT,
    source_hash        TEXT,
    sync_state         TEXT NOT NULL DEFAULT 'pending'
                       CHECK (sync_state IN ({", ".join(f"'{s}'" for s in SYNC_STATES)})),
    last_seen          TEXT NOT NULL
)
"""

MODEL_RUNS = """
CREATE TABLE IF NOT EXISTS model_runs (
    run_id            TEXT PRIMARY KEY,
    provider          TEXT NOT NULL,
    model             TEXT,
    task_type         TEXT NOT NULL,
    persona           TEXT,
    started_at        TEXT NOT NULL,
    duration_ms       INTEGER,
    success           INTEGER NOT NULL,
    input_tokens_est  INTEGER,
    output_tokens_est INTEGER,
    fallback_from     TEXT,
    error             TEXT
)
"""

NOTEBOOKS = """
CREATE TABLE notebooks (
    course      TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL,
    created_at  TEXT NOT NULL
)
"""

EVIDENCE_TYPES = ("explained", "applied", "transferred", "failed", "misconception")
EVIDENCE_STRENGTHS = ("weak", "moderate", "strong")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


# prerequisites and exam_tags are JSON arrays of strings.
CONCEPTS = """
CREATE TABLE concepts (
    concept_id    TEXT PRIMARY KEY,
    course        TEXT NOT NULL,
    name          TEXT NOT NULL,
    module        TEXT,
    prerequisites TEXT NOT NULL DEFAULT '[]',
    exam_tags     TEXT NOT NULL DEFAULT '[]'
)
"""

MASTERY = """
CREATE TABLE mastery (
    concept_id           TEXT PRIMARY KEY REFERENCES concepts (concept_id),
    level                INTEGER NOT NULL CHECK (level BETWEEN 0 AND 5),
    confidence           REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    evidence_count       INTEGER NOT NULL DEFAULT 0,
    last_evidence_at     TEXT,
    retention_confidence REAL CHECK (retention_confidence BETWEEN 0 AND 1),
    last_reviewed        TEXT
)
"""

EVIDENCE = f"""
CREATE TABLE evidence (
    evidence_id     TEXT PRIMARY KEY,
    concept_id      TEXT NOT NULL REFERENCES concepts (concept_id),
    session_id      TEXT,
    type            TEXT NOT NULL CHECK (type IN ({_in(EVIDENCE_TYPES)})),
    strength        TEXT NOT NULL CHECK (strength IN ({_in(EVIDENCE_STRENGTHS)})),
    source_provider TEXT,
    excerpt_ref     TEXT,
    recorded_at     TEXT NOT NULL
)
"""

SESSIONS = """
CREATE TABLE sessions (
    session_id        TEXT PRIMARY KEY,
    course            TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    ended_at          TEXT,
    tutor_provider    TEXT,
    analyzer_provider TEXT,
    summary_path      TEXT
)
"""

# Evidence is append-only (principle 4: every mastery change points at rows that never change).
EVIDENCE_APPEND_ONLY = (
    "CREATE TRIGGER evidence_no_update BEFORE UPDATE ON evidence"
    " BEGIN SELECT RAISE(ABORT, 'evidence is append-only'); END",
    "CREATE TRIGGER evidence_no_delete BEFORE DELETE ON evidence"
    " BEGIN SELECT RAISE(ABORT, 'evidence is append-only'); END",
)

MASTERY_CHANGERS = ("analyzer", "manual")

# Principle 4 audit trail: one row per set_mastery call, naming the evidence that justified it.
MASTERY_HISTORY = f"""
CREATE TABLE mastery_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id   TEXT NOT NULL REFERENCES concepts (concept_id),
    old_level    INTEGER CHECK (old_level BETWEEN 0 AND 5),
    new_level    INTEGER NOT NULL CHECK (new_level BETWEEN 0 AND 5),
    confidence   REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    evidence_ids TEXT NOT NULL,
    changed_at   TEXT NOT NULL,
    changed_by   TEXT NOT NULL CHECK (changed_by IN ({_in(MASTERY_CHANGERS)}))
)
"""

MASTERY_HISTORY_APPEND_ONLY = (
    "CREATE TRIGGER mastery_history_no_update BEFORE UPDATE ON mastery_history"
    " BEGIN SELECT RAISE(ABORT, 'mastery_history is append-only'); END",
    "CREATE TRIGGER mastery_history_no_delete BEFORE DELETE ON mastery_history"
    " BEGIN SELECT RAISE(ABORT, 'mastery_history is append-only'); END",
)

CHALLENGE_STATUSES = ("pending", "asked", "answered", "resolved")

# A disagreement about a concept's level becomes one Challenger probe (BL-030).
CHALLENGES = f"""
CREATE TABLE challenges (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id TEXT NOT NULL REFERENCES concepts (concept_id),
    session_id TEXT,
    reason     TEXT NOT NULL,
    question   TEXT,
    status     TEXT NOT NULL DEFAULT 'pending'
               CHECK (status IN ({_in(CHALLENGE_STATUSES)})),
    created_at TEXT NOT NULL
)
"""

# Which concepts each generated episode targeted (a JSON array of concept ids), so later evidence
# can be tied back to it (BL-034).
PODCASTS = """
CREATE TABLE podcasts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    course           TEXT NOT NULL,
    concepts         TEXT NOT NULL,
    instruction_path TEXT NOT NULL,
    audio_path       TEXT NOT NULL,
    created_at       TEXT NOT NULL
)
"""

BENCHMARK_METRICS = (
    "accuracy",
    "groundedness",
    "format_compliance",
    "latency_ms",
    "learner_rating",
)

# Raw, append-only measurements; the `benchmarks` view aggregates them per provider and task type
# (principle 8: routing reads measured strengths). sample_count is the number of runs measured.
BENCHMARK_SAMPLES = f"""
CREATE TABLE benchmark_samples (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    provider    TEXT NOT NULL,
    task_type   TEXT NOT NULL,
    metric      TEXT NOT NULL CHECK (metric IN ({_in(BENCHMARK_METRICS)})),
    value       REAL NOT NULL,
    recorded_at TEXT NOT NULL
)
"""

BENCHMARKS_VIEW = """
CREATE VIEW benchmarks AS
SELECT provider,
       task_type,
       avg(CASE WHEN metric = 'accuracy' THEN value END)          AS accuracy,
       avg(CASE WHEN metric = 'groundedness' THEN value END)      AS groundedness,
       avg(CASE WHEN metric = 'format_compliance' THEN value END) AS format_compliance,
       avg(CASE WHEN metric = 'latency_ms' THEN value END)        AS latency_ms,
       avg(CASE WHEN metric = 'learner_rating' THEN value END)    AS learner_rating,
       sum(CASE WHEN metric = 'format_compliance' THEN 1 ELSE 0 END) AS sample_count
FROM benchmark_samples
GROUP BY provider, task_type
"""

BENCHMARK_SAMPLES_APPEND_ONLY = (
    "CREATE TRIGGER benchmark_samples_no_update BEFORE UPDATE ON benchmark_samples"
    " BEGIN SELECT RAISE(ABORT, 'benchmark_samples is append-only'); END",
    "CREATE TRIGGER benchmark_samples_no_delete BEFORE DELETE ON benchmark_samples"
    " BEGIN SELECT RAISE(ABORT, 'benchmark_samples is append-only'); END",
)

# The router's last word on each provider: rate-limit cooldowns survive between commands.
PROVIDER_HEALTH = """
CREATE TABLE provider_health (
    provider       TEXT PRIMARY KEY,
    state          TEXT NOT NULL,
    checked_at     TEXT NOT NULL,
    cooldown_until TEXT,
    detail         TEXT
)
"""

MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        RESOURCES,
        "CREATE INDEX resources_course ON resources (course, bucket)",
        MODEL_RUNS,
        NOTEBOOKS,
    ),
    2: (
        CONCEPTS,
        "CREATE INDEX concepts_course ON concepts (course)",
        MASTERY,
        EVIDENCE,
        "CREATE INDEX evidence_concept ON evidence (concept_id, recorded_at)",
        *EVIDENCE_APPEND_ONLY,
        SESSIONS,
    ),
    3: (
        MASTERY_HISTORY,
        "CREATE INDEX mastery_history_concept ON mastery_history (concept_id, changed_at)",
        *MASTERY_HISTORY_APPEND_ONLY,
    ),
    4: (
        CHALLENGES,
        # At most one open challenge per concept: a second disagreement collapses into it.
        "CREATE UNIQUE INDEX challenges_one_open ON challenges (concept_id)"
        " WHERE status != 'resolved'",
    ),
    # The ExamSpec selects concepts by week (BL-031); `concepts apply` fills it from the draft.
    5: ("ALTER TABLE concepts ADD COLUMN week INTEGER",),
    6: (PODCASTS,),
    7: (
        BENCHMARK_SAMPLES,
        "CREATE INDEX benchmark_samples_task ON benchmark_samples (task_type, provider)",
        *BENCHMARK_SAMPLES_APPEND_ONLY,
        BENCHMARKS_VIEW,
        PROVIDER_HEALTH,
    ),
}

SCHEMA_VERSION = max(MIGRATIONS)
