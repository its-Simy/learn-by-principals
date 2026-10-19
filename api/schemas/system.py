"""Health, personas, the usage dashboard, doctor and jobs; and the text body every router uses."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from api.engine import Job, JobKind, JobStatus
from core.doctor import Check, Status
from core.personas import Persona
from core.providers.state import ProviderState
from core.router.benchmarks import Benchmark
from core.router.health import HealthRecord
from dashboard.data import DashboardData, ProviderRuns, WeakConcept


class TextIn(BaseModel):
    """A text file's new contents (a concept draft)."""

    text: str


# One model for every router, so the OpenAPI document (and the web types) have one TextOut.
class TextOut(BaseModel):
    """A text file's contents: a transcript, a draft, its diff, an exam paper or a brief."""

    text: str


class HealthOut(BaseModel):
    ok: bool
    version: str
    schema_version: int
    term: str  # config.term: what a new course is filed under when it names no term


class PersonaOut(BaseModel):
    name: str
    group: str  # "teaching" personas are the ones a tutor session can start with
    task_types: list[str]
    min_anchor_level: int | None

    @classmethod
    def from_core(cls, persona: Persona) -> PersonaOut:
        return cls(
            name=persona.name,
            group=persona.group,
            task_types=list(persona.task_types),
            min_anchor_level=persona.min_anchor_level,
        )


class CheckOut(BaseModel):
    name: str
    status: Status
    detail: str

    @classmethod
    def from_core(cls, check: Check) -> CheckOut:
        return cls(name=check.name, status=check.status, detail=check.detail)


class ProviderRunsOut(BaseModel):
    provider: str
    calls: int
    failures: int
    median_ms: int | None
    fallbacks: int

    @classmethod
    def from_core(cls, runs: ProviderRuns) -> ProviderRunsOut:
        return cls(
            provider=runs.provider,
            calls=runs.calls,
            failures=runs.failures,
            median_ms=runs.median_ms,
            fallbacks=runs.fallbacks,
        )


class ProviderHealthOut(BaseModel):
    """What the top bar's health dots show: a cooldown says when a rate limit ends."""

    provider: str
    state: ProviderState
    checked_at: datetime
    cooldown_until: datetime | None
    detail: str | None

    @classmethod
    def from_core(cls, record: HealthRecord) -> ProviderHealthOut:
        return cls(
            provider=record.provider,
            state=record.state,
            checked_at=record.checked_at,
            cooldown_until=record.cooldown_until,
            detail=record.detail,
        )


class BenchmarkOut(BaseModel):
    provider: str
    task_type: str
    accuracy: float | None
    groundedness: float | None
    format_compliance: float | None
    latency_ms: float | None
    learner_rating: float | None
    sample_count: int
    score: float | None  # the composite the router ranks by

    @classmethod
    def from_core(cls, mark: Benchmark) -> BenchmarkOut:
        return cls(
            provider=mark.provider,
            task_type=mark.task_type,
            accuracy=mark.accuracy,
            groundedness=mark.groundedness,
            format_compliance=mark.format_compliance,
            latency_ms=mark.latency_ms,
            learner_rating=mark.learner_rating,
            sample_count=mark.sample_count,
            score=mark.score,
        )


class WeakConceptOut(BaseModel):
    course: str
    name: str
    level: int
    confidence: float
    retention: float | None

    @classmethod
    def from_core(cls, concept: WeakConcept) -> WeakConceptOut:
        return cls(
            course=concept.course,
            name=concept.name,
            level=concept.level,
            confidence=concept.confidence,
            retention=concept.retention,
        )


class DashboardOut(BaseModel):
    """``dashboard.data.DashboardData``, field for field."""

    generated_at: datetime
    today: list[ProviderRunsOut]
    week: list[ProviderRunsOut]
    health: list[ProviderHealthOut]
    benchmarks: list[BenchmarkOut]
    artifacts_week: dict[str, int]
    artifacts_total: dict[str, int]
    podcasts: int
    sync: dict[str, dict[str, int]]  # course -> sync state -> count
    weakest: list[WeakConceptOut]

    @classmethod
    def from_core(cls, data: DashboardData) -> DashboardOut:
        return cls(
            generated_at=data.generated_at,
            today=[ProviderRunsOut.from_core(r) for r in data.today],
            week=[ProviderRunsOut.from_core(r) for r in data.week],
            health=[ProviderHealthOut.from_core(h) for h in data.health],
            benchmarks=[BenchmarkOut.from_core(b) for b in data.benchmarks],
            artifacts_week=dict(data.artifacts_week),
            artifacts_total=dict(data.artifacts_total),
            podcasts=data.podcasts,
            sync={course: dict(states) for course, states in data.sync.items()},
            weakest=[WeakConceptOut.from_core(w) for w in data.weakest],
        )


class JobOut(BaseModel):
    """A queued or finished job; the UI polls ``/api/jobs/{id}`` until ``done`` or ``failed``."""

    id: str
    kind: JobKind
    course: str
    status: JobStatus
    created_at: str
    started_at: str | None
    finished_at: str | None
    result: dict[str, Any] | None
    error: str | None

    @classmethod
    def from_core(cls, job: Job) -> JobOut:
        return cls(
            id=job.id,
            kind=job.kind,
            course=job.course,
            status=job.status,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            result=job.result,
            error=job.error,
        )
