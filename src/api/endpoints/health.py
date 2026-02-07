"""Pipeline health assessment endpoints.

Evaluates individual project health and aggregate pipeline health,
identifying at-risk projects and providing actionable diagnostics.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.dependencies import DbSession, PaginationDep
from src.models.barrier import ProjectBarrier
from src.models.enums import OverallHealth, PipelineStage
from src.models.project import Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class HealthDimension(BaseModel):
    """Score for a single health dimension."""

    dimension: str = Field(..., description="Name of the health dimension")
    score: float = Field(..., ge=0, le=100, description="Score from 0 (worst) to 100 (best)")
    status: str = Field(..., description="Qualitative status label")
    detail: str = Field("", description="Human-readable explanation")

    model_config = {"from_attributes": True}


class ProjectHealthResponse(BaseModel):
    """Detailed health assessment for a single project."""

    project_id: uuid.UUID
    project_name: str
    current_stage: PipelineStage
    overall_health: OverallHealth | None = None
    health_score: float | None = Field(None, ge=0, le=100)
    assessed_at: str

    dimensions: list[HealthDimension]
    top_risks: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class AtRiskProject(BaseModel):
    """Summary of an at-risk project."""

    project_id: uuid.UUID
    project_name: str
    city: str | None = None
    state: str | None = None
    jurisdiction: str | None = None
    current_stage: PipelineStage
    overall_health: OverallHealth | None = None
    health_score: float | None = None
    days_in_current_stage: int | None = None
    funding_gap: float | None = None
    primary_risk: str | None = None

    model_config = {"from_attributes": True}


class AtRiskListResponse(BaseModel):
    """Paginated list of at-risk projects."""

    items: list[AtRiskProject]
    total: int
    limit: int
    offset: int

    model_config = {"from_attributes": True}


class PipelineHealthSummary(BaseModel):
    """Aggregate pipeline health across the portfolio."""

    generated_at: str
    jurisdiction: str | None = None
    state: str | None = None

    total_projects: int
    on_track_count: int
    on_track_pct: float
    at_risk_count: int
    at_risk_pct: float
    delayed_count: int
    delayed_pct: float
    stalled_count: int
    stalled_pct: float

    avg_health_score: float | None = None
    total_funding_gap: float = 0.0
    total_friction_cost: float = 0.0

    most_common_risk_factors: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _score_timeline(project: Project) -> HealthDimension:
    """Score how the project is tracking against its timeline."""
    score = 80.0  # default assumption
    details: list[str] = []

    days = project.days_in_current_stage
    if days is not None:
        # Compare against loose thresholds by stage.
        thresholds = {
            PipelineStage.CONCEPT: 180,
            PipelineStage.PRE_DEVELOPMENT: 270,
            PipelineStage.ENTITLEMENT: 365,
            PipelineStage.FINANCING: 270,
            PipelineStage.CONSTRUCTION: 730,
            PipelineStage.LEASE_UP: 180,
        }
        threshold = thresholds.get(project.current_stage, 365)
        ratio = days / threshold
        if ratio > 1.5:
            score = max(score - 60, 0)
            details.append(f"Significantly over expected duration ({days} days vs ~{threshold})")
        elif ratio > 1.0:
            score = max(score - 30, 0)
            details.append(f"Over expected duration ({days} days vs ~{threshold})")
        else:
            details.append(f"Within expected duration ({days} of ~{threshold} days)")

    if project.current_stage in (PipelineStage.STALLED, PipelineStage.ABANDONED):
        score = 0
        details.append(f"Project is {project.current_stage.value}")

    status_label = "good" if score >= 70 else "concern" if score >= 40 else "critical"
    return HealthDimension(
        dimension="timeline",
        score=round(score, 1),
        status=status_label,
        detail="; ".join(details) if details else "Insufficient timeline data",
    )


def _score_funding(project: Project) -> HealthDimension:
    """Score financial health based on funding gap and committed funds."""
    score = 85.0
    details: list[str] = []

    tdc = float(project.total_development_cost or 0)
    gap = float(project.funding_gap or 0)
    committed = float(project.total_funding_committed or 0)

    if tdc > 0 and gap > 0:
        gap_pct = gap / tdc * 100
        if gap_pct > 40:
            score = max(score - 60, 0)
            details.append(f"Funding gap is {gap_pct:.0f}% of TDC (${gap:,.0f})")
        elif gap_pct > 20:
            score = max(score - 35, 0)
            details.append(f"Funding gap is {gap_pct:.0f}% of TDC (${gap:,.0f})")
        elif gap_pct > 5:
            score = max(score - 15, 0)
            details.append(f"Modest funding gap ({gap_pct:.0f}% of TDC)")
        else:
            details.append("Funding nearly fully committed")
    elif tdc > 0 and gap <= 0:
        score = 95.0
        details.append("No funding gap")
    else:
        score = 50.0
        details.append("Insufficient cost/funding data")

    status_label = "good" if score >= 70 else "concern" if score >= 40 else "critical"
    return HealthDimension(
        dimension="funding",
        score=round(score, 1),
        status=status_label,
        detail="; ".join(details) if details else "No funding data available",
    )


def _score_regulatory(project: Project) -> HealthDimension:
    """Score regulatory friction risk."""
    score = 80.0
    details: list[str] = []

    friction = project.jurisdiction_friction_score
    if friction is not None:
        if friction > 75:
            score = max(score - 50, 0)
            details.append(f"High friction jurisdiction (score: {friction})")
        elif friction > 50:
            score = max(score - 25, 0)
            details.append(f"Moderate friction jurisdiction (score: {friction})")
        else:
            details.append(f"Low friction jurisdiction (score: {friction})")

    if project.appeals_filed and project.appeals_filed > 0:
        score = max(score - 15 * project.appeals_filed, 0)
        details.append(f"{project.appeals_filed} appeal(s) filed")

    opposition = project.neighbor_opposition_level
    if opposition and opposition.value in ("high", "severe"):
        score = max(score - 20, 0)
        details.append(f"Neighbor opposition: {opposition.value}")

    status_label = "good" if score >= 70 else "concern" if score >= 40 else "critical"
    return HealthDimension(
        dimension="regulatory",
        score=round(score, 1),
        status=status_label,
        detail="; ".join(details) if details else "No regulatory friction data",
    )


def _score_data_quality(project: Project) -> HealthDimension:
    """Score data completeness and freshness."""
    score = 70.0
    details: list[str] = []

    completeness = project.data_completeness
    if completeness is not None:
        score = completeness * 100
        details.append(f"Data completeness: {completeness:.0%}")
    else:
        details.append("Data completeness unknown")

    if project.last_verified:
        staleness = (date.today() - project.last_verified).days
        if staleness > 180:
            score = max(score - 20, 0)
            details.append(f"Last verified {staleness} days ago (stale)")
        elif staleness > 90:
            score = max(score - 10, 0)
            details.append(f"Last verified {staleness} days ago")
        else:
            details.append(f"Recently verified ({staleness} days ago)")

    status_label = "good" if score >= 70 else "concern" if score >= 40 else "critical"
    return HealthDimension(
        dimension="data_quality",
        score=round(score, 1),
        status=status_label,
        detail="; ".join(details) if details else "No data quality information",
    )


def _compute_project_health(project: Project) -> tuple[list[HealthDimension], float]:
    """Run all scoring dimensions and compute a weighted aggregate."""
    timeline = _score_timeline(project)
    funding = _score_funding(project)
    regulatory = _score_regulatory(project)
    data_quality = _score_data_quality(project)

    dimensions = [timeline, funding, regulatory, data_quality]

    # Weighted average: timeline 35%, funding 30%, regulatory 25%, data 10%.
    weights = [0.35, 0.30, 0.25, 0.10]
    aggregate = sum(d.score * w for d, w in zip(dimensions, weights))
    return dimensions, round(aggregate, 1)


def _derive_health_label(score: float) -> OverallHealth:
    """Map a numeric score to an OverallHealth enum value."""
    if score >= 70:
        return OverallHealth.ON_TRACK
    if score >= 50:
        return OverallHealth.AT_RISK
    if score >= 25:
        return OverallHealth.DELAYED
    return OverallHealth.STALLED


def _derive_risks_and_actions(
    project: Project, dimensions: list[HealthDimension]
) -> tuple[list[str], list[str]]:
    """Generate risk descriptions and recommended actions."""
    risks: list[str] = []
    actions: list[str] = []

    for dim in dimensions:
        if dim.status == "critical":
            risks.append(f"Critical {dim.dimension}: {dim.detail}")
        elif dim.status == "concern":
            risks.append(f"{dim.dimension.capitalize()} concern: {dim.detail}")

    # Specific action suggestions.
    funding_dim = next((d for d in dimensions if d.dimension == "funding"), None)
    if funding_dim and funding_dim.score < 50:
        actions.append("Identify additional funding sources to close the gap")

    timeline_dim = next((d for d in dimensions if d.dimension == "timeline"), None)
    if timeline_dim and timeline_dim.score < 40:
        actions.append("Escalate timeline review with development team")

    reg_dim = next((d for d in dimensions if d.dimension == "regulatory"), None)
    if reg_dim and reg_dim.score < 50:
        actions.append("Engage with jurisdiction to resolve regulatory barriers")

    dq_dim = next((d for d in dimensions if d.dimension == "data_quality"), None)
    if dq_dim and dq_dim.score < 50:
        actions.append("Update and verify project data")

    if not actions:
        actions.append("Continue monitoring -- project appears healthy")

    return risks, actions


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}",
    response_model=ProjectHealthResponse,
    summary="Assess project health",
)
def assess_project_health(
    project_id: uuid.UUID,
    db: DbSession,
) -> ProjectHealthResponse:
    """Perform a multi-dimensional health assessment for a single project.

    Scoring dimensions:

    * **Timeline** (35 %) -- Is the project progressing through its current
      stage at a reasonable pace?
    * **Funding** (30 %) -- How large is the remaining funding gap relative
      to total development cost?
    * **Regulatory** (25 %) -- What is the jurisdiction friction score, and
      are there active appeals or community opposition?
    * **Data quality** (10 %) -- How complete and fresh is the project data?

    When ``src.analytics.assess_pipeline_health`` is available it is used
    for a richer assessment backed by ML.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    # Try the analytics module.
    try:
        from src.analytics import assess_pipeline_health
        result = assess_pipeline_health(db, project_id=project_id)
        return ProjectHealthResponse(
            project_id=project.project_id,
            project_name=project.project_name,
            current_stage=project.current_stage,
            overall_health=result.get("overall_health"),
            health_score=result.get("health_score"),
            assessed_at=datetime.utcnow().isoformat(),
            dimensions=[HealthDimension(**d) for d in result.get("dimensions", [])],
            top_risks=result.get("top_risks", []),
            recommended_actions=result.get("recommended_actions", []),
        )
    except (ImportError, AttributeError):
        pass

    dimensions, aggregate_score = _compute_project_health(project)
    health_label = _derive_health_label(aggregate_score)
    risks, actions = _derive_risks_and_actions(project, dimensions)

    return ProjectHealthResponse(
        project_id=project.project_id,
        project_name=project.project_name,
        current_stage=project.current_stage,
        overall_health=health_label,
        health_score=aggregate_score,
        assessed_at=datetime.utcnow().isoformat(),
        dimensions=dimensions,
        top_risks=risks,
        recommended_actions=actions,
    )


@router.get(
    "/at-risk",
    response_model=AtRiskListResponse,
    summary="List at-risk projects",
)
def list_at_risk_projects(
    db: DbSession,
    pagination: PaginationDep,
    jurisdiction: str | None = Query(None, description="Filter by jurisdiction"),
    state: str | None = Query(None, max_length=2, description="Filter by state"),
    min_days_stalled: int | None = Query(
        None, ge=1, description="Minimum days in current stage"
    ),
    include_stalled: bool = Query(
        True, description="Include projects with STALLED stage"
    ),
) -> AtRiskListResponse:
    """Return projects that are at risk, delayed, or stalled.

    Useful for a "watch list" dashboard that surfaces projects needing
    immediate attention.
    """
    health_filter = [OverallHealth.AT_RISK, OverallHealth.DELAYED]
    if include_stalled:
        health_filter.append(OverallHealth.STALLED)

    stmt = select(Project).where(
        Project.overall_health.in_(health_filter),
    )
    if jurisdiction:
        stmt = stmt.where(Project.jurisdiction == jurisdiction)
    if state:
        stmt = stmt.where(Project.state == state.upper())
    if min_days_stalled is not None:
        stmt = stmt.where(Project.days_in_current_stage >= min_days_stalled)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0

    stmt = stmt.order_by(Project.health_score.asc().nullslast())
    stmt = stmt.limit(pagination.limit).offset(pagination.offset)
    projects = list(db.scalars(stmt).all())

    items: list[AtRiskProject] = []
    for p in projects:
        primary_risk: str | None = None
        if p.funding_gap and float(p.funding_gap) > 0:
            primary_risk = f"Funding gap: ${float(p.funding_gap):,.0f}"
        elif p.days_in_current_stage and p.days_in_current_stage > 365:
            primary_risk = f"Stalled: {p.days_in_current_stage} days in {p.current_stage.value}"
        elif p.jurisdiction_friction_score and p.jurisdiction_friction_score > 70:
            primary_risk = f"High friction score: {p.jurisdiction_friction_score}"

        items.append(
            AtRiskProject(
                project_id=p.project_id,
                project_name=p.project_name,
                city=p.city,
                state=p.state,
                jurisdiction=p.jurisdiction,
                current_stage=p.current_stage,
                overall_health=p.overall_health,
                health_score=p.health_score,
                days_in_current_stage=p.days_in_current_stage,
                funding_gap=float(p.funding_gap) if p.funding_gap else None,
                primary_risk=primary_risk,
            )
        )

    return AtRiskListResponse(
        items=items,
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get(
    "/summary",
    response_model=PipelineHealthSummary,
    summary="Pipeline health summary",
)
def get_pipeline_health_summary(
    db: DbSession,
    jurisdiction: str | None = Query(None, description="Filter by jurisdiction"),
    state: str | None = Query(None, max_length=2, description="Filter by state"),
) -> PipelineHealthSummary:
    """Get aggregate pipeline health metrics across the portfolio.

    Returns counts and percentages for each health category, average health
    score, total funding gap, total friction costs, and the most frequently
    occurring risk factors.
    """
    conditions = [Project.project_id.isnot(None)]
    if jurisdiction:
        conditions.append(Project.jurisdiction == jurisdiction)
    if state:
        conditions.append(Project.state == state.upper())

    from sqlalchemy import and_
    base_filter = and_(*conditions)

    # Total projects.
    total = db.scalar(select(func.count()).where(base_filter)) or 0

    # Health distribution.
    health_stmt = (
        select(Project.overall_health, func.count(Project.project_id).label("cnt"))
        .where(base_filter)
        .group_by(Project.overall_health)
    )
    health_rows = {r.overall_health: r.cnt for r in db.execute(health_stmt).all()}

    on_track = health_rows.get(OverallHealth.ON_TRACK, 0)
    at_risk = health_rows.get(OverallHealth.AT_RISK, 0)
    delayed = health_rows.get(OverallHealth.DELAYED, 0)
    stalled = health_rows.get(OverallHealth.STALLED, 0)

    def _pct(n: int) -> float:
        return round(n / total * 100, 1) if total > 0 else 0.0

    # Aggregates.
    agg_stmt = select(
        func.avg(Project.health_score).label("avg_hs"),
        func.coalesce(func.sum(Project.funding_gap), 0).label("total_gap"),
        func.coalesce(func.sum(Project.friction_induced_costs), 0).label("total_friction"),
    ).where(base_filter)
    agg = db.execute(agg_stmt).first()

    # Most common risk factors (from the JSON risk_factors column).
    # We surface the barrier types with the highest total occurrence count as a proxy.
    barrier_stmt = (
        select(
            ProjectBarrier.barrier_type,
            func.count(ProjectBarrier.barrier_id).label("cnt"),
        )
        .group_by(ProjectBarrier.barrier_type)
        .order_by(func.count(ProjectBarrier.barrier_id).desc())
        .limit(5)
    )
    if jurisdiction:
        barrier_stmt = barrier_stmt.where(ProjectBarrier.jurisdiction == jurisdiction)
    if state:
        barrier_stmt = barrier_stmt.join(
            Project, Project.project_id == ProjectBarrier.project_id
        ).where(Project.state == state.upper())

    common_risks = [r.barrier_type for r in db.execute(barrier_stmt).all()]

    return PipelineHealthSummary(
        generated_at=datetime.utcnow().isoformat(),
        jurisdiction=jurisdiction,
        state=state,
        total_projects=total,
        on_track_count=on_track,
        on_track_pct=_pct(on_track),
        at_risk_count=at_risk,
        at_risk_pct=_pct(at_risk),
        delayed_count=delayed,
        delayed_pct=_pct(delayed),
        stalled_count=stalled,
        stalled_pct=_pct(stalled),
        avg_health_score=round(float(agg.avg_hs), 1) if agg and agg.avg_hs else None,
        total_funding_gap=float(agg.total_gap) if agg else 0.0,
        total_friction_cost=float(agg.total_friction) if agg else 0.0,
        most_common_risk_factors=common_risks,
    )
