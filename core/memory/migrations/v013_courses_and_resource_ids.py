"""v13: courses are rows of their own, and resources are keyed by our own id (BL-042).

Course files are now uploaded by hand, so the LMS topic id and the LMS-only columns go.
``resources`` is rebuilt the v9 way: every old row is copied first (principle 3), keeping its
file, hash and NotebookLM link, with ``topic:{id}`` as its id; ``pending`` had no file, so it
becomes ``failed``. Each course already in the manifest gets a ``courses`` row whose term is
read from its stored files' paths.

Committed: never edit this file. Schema changes go in a new migration."""

STATEMENTS = (
    """
CREATE TABLE courses (
    course     TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    term       TEXT NOT NULL,
    created_at TEXT NOT NULL
)
""",
    """
CREATE TABLE resources_v13 (
    resource_id        TEXT PRIMARY KEY,
    course             TEXT NOT NULL,
    title              TEXT NOT NULL,
    filename           TEXT,
    bucket             TEXT,
    local_path         TEXT,
    hash               TEXT,
    size               INTEGER,
    url                TEXT,
    notebook_id        TEXT,
    notebook_source_id TEXT,
    source_hash        TEXT,
    sync_state         TEXT NOT NULL DEFAULT 'synced'
                       CHECK (sync_state IN ('synced', 'stale', 'failed', 'link', 'deferred')),
    added_at           TEXT NOT NULL
)
""",
    """
INSERT INTO resources_v13 (resource_id, course, title, filename, bucket, local_path, hash, size,
    url, notebook_id, notebook_source_id, source_hash, sync_state, added_at)
SELECT 'topic:' || topic_id, course, title, filename, bucket, local_path, hash, size,
    url, notebook_id, notebook_source_id, source_hash,
    CASE sync_state WHEN 'pending' THEN 'failed' ELSE sync_state END, last_seen
FROM resources ORDER BY topic_id
""",
    # local_path is storage_root/{term}/{course}/{bucket}/{filename}: the term is the last path
    # segment of `prefix` (everything before "/{course}/"). rtrim(x, replace(x, '/', '')) strips
    # x's trailing non-slash characters, leaving x up to its last '/'; what follows is that
    # segment. A course with no stored file (only links, or nothing parseable) gets 'unknown'.
    """
INSERT INTO courses (course, name, term, created_at)
SELECT course, course,
    coalesce(max(nullif(substr(prefix, length(rtrim(prefix, replace(prefix, '/', ''))) + 1), '')),
             'unknown'),
    min(last_seen)
FROM (
    SELECT course, last_seen,
           substr(local_path, 1, instr(local_path, '/' || course || '/') - 1) AS prefix
    FROM resources
)
GROUP BY course
""",
    "DROP TABLE resources",
    "ALTER TABLE resources_v13 RENAME TO resources",
    "CREATE INDEX resources_course ON resources (course, bucket)",
)
