"""SQLite DDL, applied as numbered migrations tracked in ``PRAGMA user_version``.

v1: the sync manifest, ledger and notebook cache. v2: learner memory. Later tables (benchmarks)
land with their phase as new migrations.
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
}

SCHEMA_VERSION = max(MIGRATIONS)
