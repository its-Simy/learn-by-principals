"""SQLite DDL. Later tables (concepts, mastery, evidence, benchmarks) land with their phase."""

SYNC_STATES = ("pending", "synced", "stale", "failed", "link")

RESOURCES = f"""
CREATE TABLE IF NOT EXISTS resources (
    course             TEXT NOT NULL,
    org_unit_id        INTEGER NOT NULL,
    topic_id           INTEGER PRIMARY KEY,
    module_path        TEXT NOT NULL,
    title              TEXT NOT NULL,
    type_identifier    TEXT NOT NULL,
    filename           TEXT,
    size               INTEGER,
    last_modified      TEXT,
    hash               TEXT,
    drive_file_id      TEXT,
    drive_bucket       TEXT,
    notebook_id        TEXT,
    notebook_source_id TEXT,
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

STATEMENTS = (
    RESOURCES,
    "CREATE INDEX IF NOT EXISTS resources_course ON resources (course, drive_bucket)",
    MODEL_RUNS,
)
