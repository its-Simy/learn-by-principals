"""v8: the maintenance log (BL-038).

Committed: never edit this file. Schema changes go in a new migration."""

STATEMENTS = (
    """
CREATE TABLE maintenance_runs (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at   TEXT NOT NULL,
    trigger  TEXT NOT NULL CHECK (trigger IN ('manual', 'auto')),
    decayed  INTEGER NOT NULL,
    archived INTEGER NOT NULL
)
""",
)
