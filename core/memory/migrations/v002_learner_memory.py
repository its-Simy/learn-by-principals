"""v2: learner memory: concepts, mastery, append-only evidence, sessions (BL-018).

Committed: never edit this file. Schema changes go in a new migration."""

STATEMENTS = (
    """
CREATE TABLE concepts (
    concept_id    TEXT PRIMARY KEY,
    course        TEXT NOT NULL,
    name          TEXT NOT NULL,
    module        TEXT,
    prerequisites TEXT NOT NULL DEFAULT '[]',
    exam_tags     TEXT NOT NULL DEFAULT '[]'
)
""",
    "CREATE INDEX concepts_course ON concepts (course)",
    """
CREATE TABLE mastery (
    concept_id           TEXT PRIMARY KEY REFERENCES concepts (concept_id),
    level                INTEGER NOT NULL CHECK (level BETWEEN 0 AND 5),
    confidence           REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    evidence_count       INTEGER NOT NULL DEFAULT 0,
    last_evidence_at     TEXT,
    retention_confidence REAL CHECK (retention_confidence BETWEEN 0 AND 1),
    last_reviewed        TEXT
)
""",
    """
CREATE TABLE evidence (
    evidence_id     TEXT PRIMARY KEY,
    concept_id      TEXT NOT NULL REFERENCES concepts (concept_id),
    session_id      TEXT,
    type            TEXT NOT NULL CHECK (type IN ('explained', 'applied', 'transferred', 'failed', 'misconception')),
    strength        TEXT NOT NULL CHECK (strength IN ('weak', 'moderate', 'strong')),
    source_provider TEXT,
    excerpt_ref     TEXT,
    recorded_at     TEXT NOT NULL
)
""",
    "CREATE INDEX evidence_concept ON evidence (concept_id, recorded_at)",
    "CREATE TRIGGER evidence_no_update BEFORE UPDATE ON evidence BEGIN SELECT RAISE(ABORT, 'evidence is append-only'); END",
    "CREATE TRIGGER evidence_no_delete BEFORE DELETE ON evidence BEGIN SELECT RAISE(ABORT, 'evidence is append-only'); END",
    """
CREATE TABLE sessions (
    session_id        TEXT PRIMARY KEY,
    course            TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    ended_at          TEXT,
    tutor_provider    TEXT,
    analyzer_provider TEXT,
    summary_path      TEXT
)
""",
)
