"""v9: mastery changes may be made by the Challenger (BL-040, P72).

SQLite can't alter a CHECK constraint, so ``mastery_history`` is rebuilt: every row is copied
into the new table before the old one is dropped (principle 3), then its index and append-only
triggers are recreated.

Committed: never edit this file. Schema changes go in a new migration."""

STATEMENTS = (
    """
CREATE TABLE mastery_history_v9 (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id   TEXT NOT NULL REFERENCES concepts (concept_id),
    old_level    INTEGER CHECK (old_level BETWEEN 0 AND 5),
    new_level    INTEGER NOT NULL CHECK (new_level BETWEEN 0 AND 5),
    confidence   REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    evidence_ids TEXT NOT NULL,
    changed_at   TEXT NOT NULL,
    changed_by   TEXT NOT NULL CHECK (changed_by IN ('analyzer', 'manual', 'challenger'))
)
""",
    "INSERT INTO mastery_history_v9 SELECT id, concept_id, old_level, new_level, confidence,"
    " evidence_ids, changed_at, changed_by FROM mastery_history ORDER BY id",
    "DROP TABLE mastery_history",
    "ALTER TABLE mastery_history_v9 RENAME TO mastery_history",
    "CREATE INDEX mastery_history_concept ON mastery_history (concept_id, changed_at)",
    "CREATE TRIGGER mastery_history_no_update BEFORE UPDATE ON mastery_history"
    " BEGIN SELECT RAISE(ABORT, 'mastery_history is append-only'); END",
    "CREATE TRIGGER mastery_history_no_delete BEFORE DELETE ON mastery_history"
    " BEGIN SELECT RAISE(ABORT, 'mastery_history is append-only'); END",
)
