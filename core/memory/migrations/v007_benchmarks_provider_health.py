"""v7: benchmark samples, the benchmarks view, provider health (BL-035).

Committed: never edit this file. Schema changes go in a new migration."""

STATEMENTS = (
    """
CREATE TABLE benchmark_samples (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    provider    TEXT NOT NULL,
    task_type   TEXT NOT NULL,
    metric      TEXT NOT NULL CHECK (metric IN ('accuracy', 'groundedness', 'format_compliance', 'latency_ms', 'learner_rating')),
    value       REAL NOT NULL,
    recorded_at TEXT NOT NULL
)
""",
    "CREATE INDEX benchmark_samples_task ON benchmark_samples (task_type, provider)",
    "CREATE TRIGGER benchmark_samples_no_update BEFORE UPDATE ON benchmark_samples BEGIN SELECT RAISE(ABORT, 'benchmark_samples is append-only'); END",
    "CREATE TRIGGER benchmark_samples_no_delete BEFORE DELETE ON benchmark_samples BEGIN SELECT RAISE(ABORT, 'benchmark_samples is append-only'); END",
    """
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
""",
    """
CREATE TABLE provider_health (
    provider       TEXT PRIMARY KEY,
    state          TEXT NOT NULL,
    checked_at     TEXT NOT NULL,
    cooldown_until TEXT,
    detail         TEXT
)
""",
)
