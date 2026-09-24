"""v11: concepts missing from a reviewed draft are retired, never deleted (BL-040, P46).

Committed: never edit this file. Schema changes go in a new migration."""

STATEMENTS = (
    "ALTER TABLE concepts ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
    " CHECK (status IN ('active', 'retired'))",
)
