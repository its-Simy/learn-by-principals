"""v1: the sync manifest, the model_runs ledger and the notebook cache (BL-009R, BL-014, BL-021).

Committed: never edit this file. Schema changes go in a new migration."""

STATEMENTS = (
    """
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
                       CHECK (sync_state IN ('pending', 'synced', 'stale', 'failed', 'link', 'deferred')),
    last_seen          TEXT NOT NULL
)
""",
    "CREATE INDEX resources_course ON resources (course, bucket)",
    """
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
""",
    """
CREATE TABLE notebooks (
    course      TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL,
    created_at  TEXT NOT NULL
)
""",
)
