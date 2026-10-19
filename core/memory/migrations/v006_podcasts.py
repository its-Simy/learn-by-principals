"""v6: podcast episodes and the concepts each targeted (BL-034).

Committed: never edit this file. Schema changes go in a new migration."""

STATEMENTS = (
    """
CREATE TABLE podcasts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    course           TEXT NOT NULL,
    concepts         TEXT NOT NULL,
    instruction_path TEXT NOT NULL,
    audio_path       TEXT NOT NULL,
    created_at       TEXT NOT NULL
)
""",
)
