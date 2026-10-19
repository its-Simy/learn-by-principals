"""Numbered SQLite migrations, one module each, applied in order and tracked in
``PRAGMA user_version`` (see ``core.memory.db.migrate``).

Rules (CLAUDE.md, BL-040): a migration is ``vNNN_<name>.py`` defining ``STATEMENTS``; numbers are
sequential integers from 1; a committed migration is never renumbered or edited, and a schema
change always gets a new file. Migration SQL is literal text: it never imports the value lists
in ``core.memory.schema``, which may grow later. ``tests/test_migrations.py`` checksums every
committed migration.
"""

from __future__ import annotations

import importlib
import pkgutil
import re

_NAME = re.compile(r"^v(\d{3})_[a-z0-9_]+$")


class MigrationError(Exception):
    pass


def load() -> dict[int, tuple[str, ...]]:
    found: dict[int, tuple[str, ...]] = {}
    for info in pkgutil.iter_modules(__path__):
        match = _NAME.match(info.name)
        if match is None:
            raise MigrationError(f"{info.name}: migrations are named vNNN_<name>.py")
        number = int(match.group(1))
        if number in found:
            raise MigrationError(f"Two migrations are numbered {number}")
        found[number] = tuple(importlib.import_module(f"{__name__}.{info.name}").STATEMENTS)
    if sorted(found) != list(range(1, len(found) + 1)):
        raise MigrationError(f"Migrations must be numbered 1..N with no gaps: {sorted(found)}")
    return dict(sorted(found.items()))


MIGRATIONS = load()
SCHEMA_VERSION = max(MIGRATIONS)
