from __future__ import annotations

import logging
import re
import sqlite3
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from core.ledger.ledger import utcnow
from core.memory.schema import MIGRATIONS, SCHEMA_VERSION

log = logging.getLogger(__name__)


class SchemaError(Exception):
    pass


def connect(path: Path | str, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """``check_same_thread=False`` is for the API's per-request connection, which FastAPI opens,
    uses and closes on different threadpool threads, one request at a time."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    migrate(conn)
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> None:
    version = schema_version(conn)
    if version > SCHEMA_VERSION:
        raise SchemaError(f"Database is at schema v{version}; this code knows v{SCHEMA_VERSION}")
    if version == 0:
        _drop_empty_legacy_manifest(conn)
    for target in sorted(v for v in MIGRATIONS if v > version):
        conn.execute("BEGIN")
        try:
            for statement in MIGRATIONS[target]:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {target}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        log.info("Database migrated to schema v%d", target)


def _drop_empty_legacy_manifest(conn: sqlite3.Connection) -> None:
    """The unversioned Drive-era ``resources`` table: dropped if empty, refused otherwise."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(resources)")}
    if "drive_file_id" not in cols:
        return
    count = conn.execute("SELECT count(*) FROM resources").fetchone()[0]
    if count:
        raise SchemaError(
            f"The database has {count} Drive-era manifest rows; there is no migration for them yet"
        )
    with conn:
        conn.execute("DROP TABLE resources")
    log.info("Dropped the empty Drive-era resources table")


@dataclass
class ResourceRow:
    resource_id: str
    course: str
    title: str
    added_at: str
    filename: str | None = None
    bucket: str | None = None
    local_path: str | None = None
    hash: str | None = None
    size: int | None = None
    url: str | None = None
    notebook_id: str | None = None
    notebook_source_id: str | None = None
    source_hash: str | None = None
    sync_state: str = "synced"


_COLUMNS = [f.name for f in fields(ResourceRow)]


class Manifest:
    """The ``resources`` table: one row per stored course file. Rows are never deleted."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, resource_id: str) -> ResourceRow | None:
        row = self.conn.execute(
            "SELECT * FROM resources WHERE resource_id = ?", (resource_id,)
        ).fetchone()
        return ResourceRow(**dict(row)) if row else None

    def upsert(self, row: ResourceRow) -> None:
        cols = ", ".join(_COLUMNS)
        marks = ", ".join(f":{c}" for c in _COLUMNS)
        updates = ", ".join(f"{c} = excluded.{c}" for c in _COLUMNS if c != "resource_id")
        with self.conn:
            self.conn.execute(
                f"INSERT INTO resources ({cols}) VALUES ({marks}) "
                f"ON CONFLICT (resource_id) DO UPDATE SET {updates}",
                asdict(row),
            )

    def find(self, course: str, bucket: str, filename: str) -> ResourceRow | None:
        """The row already stored as ``filename`` in this course bucket: a re-upload of that
        name is a new version of the same file."""
        row = self.conn.execute(
            "SELECT * FROM resources WHERE course = ? AND bucket = ? AND filename = ?"
            " ORDER BY added_at, resource_id LIMIT 1",
            (course, bucket, filename),
        ).fetchone()
        return ResourceRow(**dict(row)) if row else None

    def all(
        self, course: str | None = None, states: Iterable[str] | None = None
    ) -> list[ResourceRow]:
        sql, args = "SELECT * FROM resources WHERE 1 = 1", []
        if course is not None:
            sql += " AND course = ?"
            args.append(course)
        if states is not None:
            states = list(states)
            sql += f" AND sync_state IN ({', '.join('?' for _ in states)})"
            args.extend(states)
        order = " ORDER BY added_at, resource_id"
        return [ResourceRow(**dict(r)) for r in self.conn.execute(sql + order, args)]


FOLDER_NAME = re.compile(r"[A-Za-z0-9_-]{1,32}")
# Names Windows reserves for devices: a folder can't be called CON or AUX there.
RESERVED_FOLDER_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)

# A derived course code keeps room for a "-NN" dedupe suffix within FOLDER_NAME's 32.
CODE_BASE_LENGTH = 28


def slug(text: str) -> str:
    """The one rule for turning a name into an identifier: concept ids, exam files, course codes."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "untitled"


class CourseError(ValueError):
    pass


class DuplicateCourse(CourseError):
    pass


class BadFolderName(CourseError):
    """A course code or term that can't be a folder name; ``field`` is ``course`` or ``term``."""

    def __init__(self, field: str, label: str, value: str) -> None:
        if value.upper() in RESERVED_FOLDER_NAMES:
            super().__init__(f"{label} {value!r} is a name Windows reserves for a device")
        else:
            super().__init__(f"{label} {value!r} must be 1-32 letters, digits, _ or -")
        self.field = field


@dataclass(frozen=True)
class CourseRow:
    course: str  # the code used in folder names and notebook titles, e.g. CSE220
    name: str
    term: str  # the folder under storage_root, e.g. Fall-2026
    created_at: str

    def root(self, storage_root: Path) -> Path:
        """Where this course's files live; the term comes from the row, not today's date."""
        return storage_root / self.term / self.course


class Courses:
    """The ``courses`` table. Files can only be imported into a course that has a row."""

    def __init__(self, conn: sqlite3.Connection, now: Callable[[], str] = utcnow) -> None:
        self.conn = conn
        self._now = now

    def add(self, course: str, name: str, term: str) -> CourseRow:
        # Code and term become folder names, so neither may carry a path separator or "..".
        for field, label, value in (("course", "course code", course), ("term", "term", term)):
            if not FOLDER_NAME.fullmatch(value) or value.upper() in RESERVED_FOLDER_NAMES:
                raise BadFolderName(field, label, value)
        if self.get(course) is not None:
            raise DuplicateCourse(f"course {course} already exists")
        row = CourseRow(course, name, term, self._now())
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO courses (course, name, term, created_at) VALUES (?, ?, ?, ?)",
                    (row.course, row.name, row.term, row.created_at),
                )
        except sqlite3.IntegrityError as exc:  # another writer added it since get()
            raise DuplicateCourse(f"course {course} already exists") from exc
        return row

    def code_for(self, name: str) -> str:
        """A code for a course named only by hand: the upper-cased slug of the name, cut to fit a
        folder name, then ``-2``, ``-3``, … while the table already has it."""
        ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
        base = re.sub(r"[^A-Z0-9]+", "-", ascii_name.upper()).strip("-")[:CODE_BASE_LENGTH]
        base = base.rstrip("-") or "COURSE"
        code, n = base, 2
        while self.get(code) is not None or code in RESERVED_FOLDER_NAMES:
            code, n = f"{base}-{n}", n + 1
        return code

    def get(self, course: str) -> CourseRow | None:
        row = self.conn.execute("SELECT * FROM courses WHERE course = ?", (course,)).fetchone()
        return CourseRow(**dict(row)) if row else None

    def all(self) -> list[CourseRow]:
        rows = self.conn.execute("SELECT * FROM courses ORDER BY course").fetchall()
        return [CourseRow(**dict(r)) for r in rows]
