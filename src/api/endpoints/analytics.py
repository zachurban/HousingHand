"""Bottleneck analysis endpoints for the affordable housing pipeline.

Surfaces systemic friction points across jurisdictions and identifies where
projects are getting stuck, helping stakeholders focus reform efforts.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from src.api.dependencies import DbSession, PaginationDep
from src.models.barrier import ProjectBarrier
from src.models.enums import OverallHealth, PipelineStage
from src.models.project import Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


# ---------------------------------------------------------------------------
# Pydantic response schemas
# ---------------------------------------------------------------------------

class StageBottleneck(BaseModel):
    """Aggregated statistics for a single pipeline stage."""

    stage: PipelineStage
    project_count: int = Field(..., description="Number of projects currently in this stage")
    median_days: float | None = Field(
        None,
        description="Median number of days projects spend in this stage",
    )
    avg_days: float | None = Field(
        None,
        description="Average number of days projects spend in this stage",
    )
    max_days: int | None = Field(
        None,
        description="Longest duration (days) any single project spent in this stage",
    )
    stalled_count: int = Field(
        0,
        description="Projects in this stage that exceed the stall threshold",
    )
    pct_of_pipeline: float = Field(
        0.0,
        description="Percentage of total active pipeline represented by this stage",
    )

    model_config = {"from_attributes": True}


class BarrierSummary(BaseModel):
    """Frequency and impact summary for a single barrier type."""

    barrier_type: str
    occurrence_count: int
    total_days_delayed: int
    avg_days_delayed: float
    total_cost_impact: float
    affected_jurisdictions: int

    model_config = {"from_attributes": True}


class JurisdictionFriction(BaseModel):
    """Friction summary for a specific jurisdiction."""

    jurisdiction: str
    project_count: int
    avg_friction_score: float | None = None
    stalled_count: int = 0
    at_risk_count: int = 0
    avg_entitlement_days: float | None = None
    total_friction_induced_costs: float | None = None

    model_config = {"from_attributes": True}


class BottleneckAnalysisResponse(BaseModel):
    """Complete bottleneck analysis result."""

    generated_at: str = Field(..., description="ISO timestamp of analysis generation")
    total_active_projects: int
    stall_threshold_days: int
    stage_bottlenecks: list[StageBottleneck]
    top_barriers: list[BarrierSummary]
    jurisdiction_friction: list[JurisdictionFriction]

    model_config = {"from_attributes": True}


class SystemicBottleneckResponse(BaseModel):
    """Response model for the systemic bottleneck identification endpoint."""

    jurisdiction: str | None
    state: str | None
    analysis_period_start: date | None
    analysis_period_end: date | None
    bottlenecks: list[dict[str, Any]]
    recommendations: list[str]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ACTIVE_STAGES = [
    PipelineStage.CONCEPT,
    PipelineStage.PRE_DEVELOPMENT,
    PipelineStage.ENTITLEMENT,
    PipelineStage.FINANCING,
    PipelineStage.CONSTRUCTION,
    PipelineStage.LEASE_UP,
]


def _compute_stage_bottlenecks(
    db: Session,
    stall_threshold_days: int,
    jurisdiction: str | None,
    state: str | None,
) -> tuple[list[StageBottleneck], int]:
    """Compute per-stage aggregation and stall counts."""
    base = select(Project).where(Project.current_stage.in_(_ACTIVE_STAGES))
    if jurisdiction:
        base = base.where(Project.jurisdiction == jurisdiction)
    if state:
        base = base.where(Project.state == state.upper())

    total_stmt = select(func.count()).select_from(base.subquery())
    total_active = db.scalar(total_stmt) or 0

    cutoff = date.today() - timedelta(days=stall_threshold_days)

    results: list[StageBottleneck] = []
    for stage in _ACTIVE_STAGES:
        stage_filter = base.where(Project.current_stage == stage)

        count_stmt = select(func.count()).select_from(stage_filter.subquery())
        count = db.scalar(count_stmt) or 0

        avg_stmt = select(func.avg(Project.days_in_current_stage)).where(
            Project.current_stage == stage,
            Project.current_stage.in_(_ACTIVE_STAGES),
        )
        if jurisdiction:
            avg_stmt = avg_stmt.where(Project.jurisdiction == jurisdiction)
        if state:
            avg_stmt = avg_stmt.where(Project.state == state.upper())
        avg_days = db.scalar(avg_stmt)

        max_stmt = select(func.max(Project.days_in_current_stage)).where(
            Project.current_stage == stage,
            Project.current_stage.in_(_ACTIVE_STAGES),
        )
        if jurisdiction:
            max_stmt = max_stmt.where(Project.jurisdiction == jurisdiction)
        if state:
            max_stmt = max_stmt.where(Project.state == state.upper())
        max_days = db.scalar(max_stmt)

        stalled_stmt = select(func.count()).where(
            Project.current_stage == stage,
            Project.stage_entry_date <= cutoff,
        )
        if jurisdiction:
            stalled_stmt = stalled_stmt.where(Project.jurisdiction == jurisdiction)
        if state:
            stalled_stmt = stalled_stmt.where(Project.state == state.upper())
        stalled = db.scalar(stalled_stmt) or 0

        pct = (count / total_active * 100) if total_active > 0 else 0.0

        results.append(
            StageBottleneck(
                stage=stage,
                project_count=count,
                median_days=None,  # Median requires window functions; avg is shown instead.
                avg_days=round(float(avg_days), 1) if avg_days is not None else None,
                max_days=int(max_days) if max_days is not None else None,
                stalled_count=stalled,
                pct_of_pipeline=round(pct, 1),
            )
        )

    return results, total_active


def _compute_barrier_summaries(
    db: Session,
    jurisdiction: str | None,
    state: str | None,
    top_n: int,
) -> list[BarrierSummary]:
    """Aggregate barrier types across all projects."""
    stmt = (
        select(
            ProjectBarrier.barrier_type,
            func.count(ProjectBarrier.barrier_id).label("occurrence_count"),
            func.sum(ProjectBarrier.days_delayed).label("total_days_delayed"),
            func.avg(ProjectBarrier.days_delayed).label("avg_days_delayed"),
            func.sum(ProjectBarrier.cost_impact).label("total_cost_impact"),
            func.count(func.distinct(ProjectBarrier.jurisdiction)).label(
                "affected_jurisdictions"
            ),
        )
        .group_by(ProjectBarrier.barrier_type)
        .order_by(func.sum(ProjectBarrier.days_delayed).desc())
    )

    if jurisdiction:
        stmt = stmt.where(ProjectBarrier.jurisdiction == jurisdiction)
    if state:
        stmt = stmt.join(Project, Project.project_id == ProjectBarrier.project_id).where(
            Project.state == state.upper()
        )

    stmt = stmt.limit(top_n)
    rows = db.execute(stmt).all()

    return [
        BarrierSummary(
            barrier_type=r.barrier_type,
            occurrence_count=r.occurrence_count,
            total_days_delayed=int(r.total_days_delayed or 0),
            avg_days_delayed=round(float(r.avg_days_delayed or 0), 1),
            total_cost_impact=float(r.total_cost_impact or 0),
            affected_jurisdictions=r.affected_jurisdictions,
        )
        for r in rows
    ]


def _compute_jurisdiction_friction(
    db: Session,
    state: str | None,
    top_n: int,
) -> list[JurisdictionFriction]:
    """Rank jurisdictions by average friction score."""
    stmt = (
        select(
            Project.jurisdiction,
            func.count(Project.project_id).label("project_count"),
            func.avg(Project.jurisdiction_friction_score).label("avg_friction_score"),
            func.sum(
                case(
                    (Project.current_stage == PipelineStage.STALLED, 1),
                    else_=0,
                )
            ).label("stalled_count"),
            func.sum(
                case(
                    (Project.overall_health == OverallHealth.AT_RISK, 1),
                    else_=0,
                )
            ).label("at_risk_count"),
            func.avg(Project.entitlement_duration_days).label("avg_entitlement_days"),
            func.sum(Project.friction_induced_costs).label("total_friction_induced_costs"),
        )
        .where(Project.jurisdiction.isnot(None))
        .group_by(Project.jurisdiction)
        .order_by(func.avg(Project.jurisdiction_friction_score).desc().nullslast())
    )

    if state:
        stmt = stmt.where(Project.state == state.upper())

    stmt = stmt.limit(top_n)
    rows = db.execute(stmt).all()

    return [
        JurisdictionFriction(
            jurisdiction=r.jurisdiction,
            project_count=r.project_count,
            avg_friction_score=round(float(r.avg_friction_score), 1) if r.avg_friction_score else None,
            stalled_count=int(r.stalled_count or 0),
            at_risk_count=int(r.at_risk_count or 0),
            avg_entitlement_days=round(float(r.avg_entitlement_days), 1) if r.avg_entitlement_days else None,
            total_friction_induced_costs=float(r.total_friction_induced_costs or 0),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/bottlenecks",
    response_model=BottleneckAnalysisResponse,
    summary="Analyze pipeline bottlenecks",
)
def analyze_bottlenecks(
    db: DbSession,
    jurisdiction: str | None = Query(None, description="Limit analysis to a jurisdiction"),
    state: str | None = Query(None, max_length=2, description="Limit analysis to a state"),
    stall_threshold_days: int = Query(
        180, ge=30, le=730, description="Days before a project is considered stalled"
    ),
    top_barriers: int = Query(10, ge=1, le=50, description="Number of top barriers to return"),
    top_jurisdictions: int = Query(15, ge=1, le=100, description="Number of top jurisdictions to return"),
) -> BottleneckAnalysisResponse:
    """Identify where affordable housing projects are getting stuck.

    This endpoint performs a multi-dimensional analysis:

    1. **Stage bottlenecks** -- Which pipeline stages accumulate the most
       projects and the longest durations?
    2. **Top barriers** -- Which regulatory friction types cause the most
       aggregate delay and cost across the tracked portfolio?
    3. **Jurisdiction friction** -- Which jurisdictions have the highest
       average friction scores, stall rates, and entitlement durations?

    The ``stall_threshold_days`` parameter controls when a project is
    considered "stalled" in its current stage.
    """
    from datetime import datetime as _dt

    stage_results, total_active = _compute_stage_bottlenecks(
        db, stall_threshold_days, jurisdiction, state
    )
    barrier_results = _compute_barrier_summaries(db, jurisdiction, state, top_barriers)
    friction_results = _compute_jurisdiction_friction(db, state, top_jurisdictions)

    return BottleneckAnalysisResponse(
        generated_at=_dt.utcnow().isoformat(),
        total_active_projects=total_active,
        stall_threshold_days=stall_threshold_days,
        stage_bottlenecks=stage_results,
        top_barriers=barrier_results,
        jurisdiction_friction=friction_results,
    )


@router.get(
    "/bottlenecks/systemic",
    response_model=SystemicBottleneckResponse,
    summary="Identify systemic bottlenecks",
)
def identify_systemic_bottlenecks(
    db: DbSession,
    jurisdiction: str | None = Query(None, description="Jurisdiction to analyze"),
    state: str | None = Query(None, max_length=2, description="State to analyze"),
    period_months: int = Query(
        24, ge=6, le=120, description="Look-back period in months"
    ),
) -> SystemicBottleneckResponse:
    """Identify systemic bottlenecks that transcend individual projects.

    Looks at patterns across the entire portfolio within the given time
    window to surface recurring regulatory friction, chronic under-funding,
    and other structural issues.  Delegates heavy computation to
    ``src.analytics.identify_systemic_bottlenecks`` when available, falling
    back to a direct database analysis otherwise.
    """
    from datetime import datetime as _dt

    period_start = date.today() - timedelta(days=period_months * 30)
    period_end = date.today()

    # Try the analytics module first.
    try:
        from src.analytics import identify_systemic_bottlenecks as _identify
        result = _identify(
            db,
            jurisdiction=jurisdiction,
            state=state,
            period_start=period_start,
            period_end=period_end,
        )
        return SystemicBottleneckResponse(**result)
    except (ImportError, AttributeError):
        pass

    # Fallback: direct DB aggregation.
    bottlenecks: list[dict[str, Any]] = []
    recommendations: list[str] = []

    # Find stages where projects are disproportionately accumulating.
    for stage in _ACTIVE_STAGES:
        stmt = select(func.count()).where(
            Project.current_stage == stage,
            Project.created_at >= period_start,
        )
        if jurisdiction:
            stmt = stmt.where(Project.jurisdiction == jurisdiction)
        if state:
            stmt = stmt.where(Project.state == state.upper())
        count = db.scalar(stmt) or 0

        avg_stmt = select(func.avg(Project.days_in_current_stage)).where(
            Project.current_stage == stage,
            Project.created_at >= period_start,
        )
        if jurisdiction:
            avg_stmt = avg_stmt.where(Project.jurisdiction == jurisdiction)
        if state:
            avg_stmt = avg_stmt.where(Project.state == state.upper())
        avg_days = db.scalar(avg_stmt)

        if count > 0:
            bottlenecks.append({
                "stage": stage.value,
                "project_count": count,
                "avg_days_in_stage": round(float(avg_days), 1) if avg_days else None,
                "severity": "high" if (avg_days and float(avg_days) > 365) else "moderate",
            })

    # Barrier-driven recommendations.
    barrier_stmt = (
        select(
            ProjectBarrier.barrier_type,
            func.count(ProjectBarrier.barrier_id).label("cnt"),
            func.sum(ProjectBarrier.days_delayed).label("total_delay"),
        )
        .where(ProjectBarrier.created_at >= period_start)
        .group_by(ProjectBarrier.barrier_type)
        .order_by(func.sum(ProjectBarrier.days_delayed).desc())
        .limit(5)
    )
    if jurisdiction:
        barrier_stmt = barrier_stmt.where(ProjectBarrier.jurisdiction == jurisdiction)

    top = db.execute(barrier_stmt).all()
    for row in top:
        recommendations.append(
            f"Address '{row.barrier_type}' -- caused {int(row.total_delay or 0)} "
            f"total days of delay across {row.cnt} occurrences."
        )

    if not recommendations:
        recommendations.append(
            "Insufficient barrier data to generate targeted recommendations."
        )

    return SystemicBottleneckResponse(
        jurisdiction=jurisdiction,
        state=state,
        analysis_period_start=period_start,
        analysis_period_end=period_end,
        bottlenecks=bottlenecks,
        recommendations=recommendations,
    )
