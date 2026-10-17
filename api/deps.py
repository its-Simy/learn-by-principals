"""FastAPI dependencies shared by every router.

Routes are plain ``def``, so FastAPI runs them in its threadpool. Anything they need from a worker
thread goes through ``engine``; everything else uses ``db``, a connection of the request's own,
as one CLI command opens one.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from api.engine import Engine
from core.config import Config
from core.memory.db import Courses, connect


def config(request: Request) -> Config:
    return request.app.state.config


ConfigDep = Annotated[Config, Depends(config)]


def engine(request: Request) -> Engine:
    return request.app.state.engine


EngineDep = Annotated[Engine, Depends(engine)]


def db(cfg: ConfigDep) -> Iterator[sqlite3.Connection]:
    """FastAPI opens this, runs the route and closes it on different threadpool threads, so the
    connection may cross threads; it is still used by one request at a time."""
    # Never capture it in a callable for the engine: it is closed after the response, and with
    # check_same_thread=False a worker using it would not fail loudly. Workers use r.conn.
    conn = connect(cfg.db_path, check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()


DbDep = Annotated[sqlite3.Connection, Depends(db)]


def course_code(course: str, conn: DbDep) -> str:
    """The ``{course}`` path parameter, upper-cased as the CLI does with ``--course``; 404 unless
    the course has a row."""
    code = course.upper()
    if Courses(conn).get(code) is None:
        raise HTTPException(404, f"No course {code}; add it first")
    return code


CourseDep = Annotated[str, Depends(course_code)]
