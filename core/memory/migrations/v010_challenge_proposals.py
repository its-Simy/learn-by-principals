"""v10: a challenge remembers the Analyzer's proposed level and the evidence behind it, so a
probe resolved in the learner's favour can apply that level (BL-040, P72).

``proposed_level`` is NULL for a challenge raised only by the tutor's estimate.
``evidence_ids`` is a JSON array.

Committed: never edit this file. Schema changes go in a new migration."""

STATEMENTS = (
    "ALTER TABLE challenges ADD COLUMN proposed_level INTEGER"
    " CHECK (proposed_level BETWEEN 0 AND 5)",
    "ALTER TABLE challenges ADD COLUMN evidence_ids TEXT NOT NULL DEFAULT '[]'",
)
