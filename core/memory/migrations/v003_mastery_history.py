"""v3: the append-only mastery audit trail (BL-028, P37).

Committed: never edit this file. Schema changes go in a new migration."""

STATEMENTS = (
    """
CREATE TABLE mastery_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id   TEXT NOT NULL REFERENCES concepts (concept_id),
    old_level    INTEGER CHECK (old_level BETWEEN 0 AND 5),
    new_level    INTEGER NOT NULL CHECK (new_level BETWEEN 0 AND 5),
    confidence   REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    evidence_ids TEXT NOT NULL,
    changed_at   TEXT NOT NULL,
    changed_by   TEXT NOT NULL CHECK (changed_by IN ('analyzer', 'manual'))
)
""",
    "CREATE INDEX mastery_history_concept ON mastery_history (concept_id, changed_at)",
    "CREATE TRIGGER mastery_history_no_update BEFORE UPDATE ON mastery_history BEGIN SELECT RAISE(ABORT, 'mastery_history is append-only'); END",
    "CREATE TRIGGER mastery_history_no_delete BEFORE DELETE ON mastery_history BEGIN SELECT RAISE(ABORT, 'mastery_history is append-only'); END",
)
