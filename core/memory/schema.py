"""SQLite DDL, applied as numbered migrations tracked in ``PRAGMA user_version``.

Later tables (concepts, mastery, evidence, benchmarks) land with their phase as new migrations.
"""

SYNC_STATES = ("pending", "synced", "stale", "failed", "link")

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

MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        RESOURCES,
        "CREATE INDEX resources_course ON resources (course, bucket)",
        MODEL_RUNS,
        NOTEBOOKS,
    ),
}

SCHEMA_VERSION = max(MIGRATIONS)
