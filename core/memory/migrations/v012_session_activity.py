"""v12: when a tutor session last had a turn, so idle sessions can be called stale or closed;
and how many sessions each maintenance run closed (BL-040, P67).

Committed: never edit this file. Schema changes go in a new migration."""

STATEMENTS = (
    "ALTER TABLE sessions ADD COLUMN last_turn_at TEXT",
    "ALTER TABLE maintenance_runs ADD COLUMN closed INTEGER NOT NULL DEFAULT 0",
)
