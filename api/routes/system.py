"""Routes that aren't about one course: health, personas, the usage dashboard, doctor, jobs."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter, HTTPException

from api.deps import ConfigDep, DbDep, EngineDep
from api.schemas.system import CheckOut, DashboardOut, HealthOut, JobOut, PersonaOut
from core import doctor, personas
from core.memory.db import schema_version
from dashboard.data import collect

router = APIRouter(tags=["system"])

try:
    VERSION = version("brightlearn")
except PackageNotFoundError:  # running from a checkout that was never installed
    VERSION = "unknown"


@router.get("/health")
def health(conn: DbDep, cfg: ConfigDep) -> HealthOut:
    """Answers once the database opens, which is what every other route needs too."""
    return HealthOut(ok=True, version=VERSION, schema_version=schema_version(conn), term=cfg.term)


@router.get("/personas")
def list_personas() -> list[PersonaOut]:
    return [PersonaOut.from_core(personas.load(name)) for name in personas.list_personas()]


@router.get("/dashboard")
def dashboard(conn: DbDep) -> DashboardOut:
    return DashboardOut.from_core(collect(conn))


@router.get("/doctor")
def run_doctor(cfg: ConfigDep) -> list[CheckOut]:
    """Read-only, like ``brightlearn doctor``: no check spends quota or changes anything."""
    return [CheckOut.from_core(c) for c in doctor.run_checks(cfg)]


@router.get("/jobs")
def list_jobs(engine: EngineDep, course: str | None = None) -> list[JobOut]:
    jobs = engine.jobs.all(course.upper() if course else None)
    return [JobOut.from_core(j) for j in jobs]


@router.get("/jobs/{job_id}")
def get_job(job_id: str, engine: EngineDep) -> JobOut:
    job = engine.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"No job {job_id}; jobs are forgotten when the server restarts")
    return JobOut.from_core(job)
