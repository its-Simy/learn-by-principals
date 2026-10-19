"""v4: Challenger probes, at most one open per concept (BL-030).

Committed: never edit this file. Schema changes go in a new migration."""

STATEMENTS = (
    """
CREATE TABLE challenges (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id TEXT NOT NULL REFERENCES concepts (concept_id),
    session_id TEXT,
    reason     TEXT NOT NULL,
    question   TEXT,
    status     TEXT NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending', 'asked', 'answered', 'resolved')),
    created_at TEXT NOT NULL
)
""",
    "CREATE UNIQUE INDEX challenges_one_open ON challenges (concept_id) WHERE status != 'resolved'",
)
