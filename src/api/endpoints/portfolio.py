"""Portfolio dashboard endpoints.

Provides aggregate portfolio views for PHAs, funders, cities, and other
stakeholders to monitor their slice of the affordable housing pipeline.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from src.api.dependencies import DbSession, PaginationDep
from src.models.enums import OverallHealth, PipelineStage, PortfolioType
from src.models.portfolio import PortfolioDashboard
from src.models.project import Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class StageDistribution(BaseModel):
    """Number of projects in each pipeline stage."""

    concept: int = 0
    pre_development: int = 0
    entitlement: int = 0
    financing: int = 0
    construction: int = 0
    lease_up: int = 0
    operations: int = 0
    stalled: int = 0
    abandoned: int = 0

    model_config = {"from_attributes": True}


class HealthDistribution(BaseModel):
    """Count of projects by overall health status."""

    on_track: int = 0
    at_risk: int = 0
    delayed: int = 0
    stalled: int = 0
    unknown: int = 0

    model_config = {"from_attributes": True}


class FundingSummary(BaseModel):
    """Aggregate funding information across the portfolio."""

    total_development_cost: float = 0.0
    total_funding_committed: float = 0.0
    total_funding_gap: float = 0.0
    total_debt: float = 0.0
    total_equity: float = 0.0
    total_subsidy: float = 0.0

    model_config = {"from_attributes": True}


class VelocityMetrics(BaseModel):
    """Pipeline throughput metrics."""

    avg_concept_to_construction_days: float | None = None
    avg_entitlement_days: float | None = None
    avg_financing_days: float | None = None
    avg_construction_days: float | None = None
    projects_completed_last_12_months: int = 0
    units_completed_last_12_months: int = 0

    model_config = {"from_attributes": True}


class PortfolioOverview(BaseModel):
    """Complete portfolio dashboard snapshot."""

    generated_at: str
    portfolio_name: str | None = None
    jurisdiction: str | None = None
    state: str | None = None

    # Headline numbers
    total_projects: int
    total_units: int
    total_affordable_units: int

    # Distributions
    stage_distribution: StageDistribution
    health_distribution: HealthDistribution

    # Funding
    funding: FundingSummary

    # Velocity
    velocity: VelocityMetrics

    # At-risk summary
    at_risk_projects: int
    stalled_projects: int

    model_config = {"from_attributes": True}


class PortfolioDashboardResponse(BaseModel):
    """Saved portfolio dashboard configuration plus cached metrics."""

    portfolio_id: uuid.UUID
    portfolio_name: str
    organization: str | None = None
    portfolio_type: PortfolioType
    total_projects: int
    total_units: int
    units_by_stage: dict[str, Any] | None = None
    funding_gap_aggregate: float | None = None
    at_risk_count: int
    velocity_metrics: dict[str, Any] | None = None
    is_public: bool
    last_calculated: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PortfolioDashboardListResponse(BaseModel):
    """Paginated list of saved portfolio dashboards."""

    items: list[PortfolioDashboardResponse]
    total: int
    limit: int
    offset: int

    model_config = {"from_attributes": True}


class PortfolioDashboardCreate(BaseModel):
    """Schema for creating a new saved portfolio dashboard."""

    portfolio_name: str = Field(..., min_length=1, max_length=300)
    organization: str | None = None
    portfolio_type: PortfolioType
    geography_filter: dict[str, Any] | None = None
    funding_filter: dict[str, Any] | None = None
    stage_filter: dict[str, Any] | None = None
    ami_filter: dict[str, Any] | None = None
    date_range_start: date | None = None
    date_range_end: date | None = None
    is_public: bool = False

    model_config = {"json_schema_extra": {
        "examples": [
            {
                "portfolio_name": "Bay Area PHA Pipeline",
                "portfolio_type": "pha_service_area",
                "organization": "Bay Area Housing Authority",
                "geography_filter": {"state": "CA", "counties": ["Alameda", "San Francisco"]},
                "is_public": True,
            }
        ]
    }}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_stage_distribution(db: Session, base_filter: Any) -> StageDistribution:
    """Compute stage distribution from a base filter expression."""
    stmt = (
        select(
            Project.current_stage,
            func.count(Project.project_id).label("cnt"),
        )
        .where(base_filter)
        .group_by(Project.current_stage)
    )
    rows = {r.current_stage: r.cnt for r in db.execute(stmt).all()}
    return StageDistribution(
        concept=rows.get(PipelineStage.CONCEPT, 0),
        pre_development=rows.get(PipelineStage.PRE_DEVELOPMENT, 0),
        entitlement=rows.get(PipelineStage.ENTITLEMENT, 0),
        financing=rows.get(PipelineStage.FINANCING, 0),
        construction=rows.get(PipelineStage.CONSTRUCTION, 0),
        lease_up=rows.get(PipelineStage.LEASE_UP, 0),
        operations=rows.get(PipelineStage.OPERATIONS, 0),
        stalled=rows.get(PipelineStage.STALLED, 0),
        abandoned=rows.get(PipelineStage.ABANDONED, 0),
    )


def _build_health_distribution(db: Session, base_filter: Any) -> HealthDistribution:
    """Compute health distribution from a base filter expression."""
    stmt = (
        select(
            Project.overall_health,
            func.count(Project.project_id).label("cnt"),
        )
        .where(base_filter)
        .group_by(Project.overall_health)
    )
    rows = {r.overall_health: r.cnt for r in db.execute(stmt).all()}
    return HealthDistribution(
        on_track=rows.get(OverallHealth.ON_TRACK, 0),
        at_risk=rows.get(OverallHealth.AT_RISK, 0),
        delayed=rows.get(OverallHealth.DELAYED, 0),
        stalled=rows.get(OverallHealth.STALLED, 0),
        unknown=rows.get(None, 0),
    )


def _build_funding_summary(db: Session, base_filter: Any) -> FundingSummary:
    """Aggregate funding data across the filtered portfolio."""
    stmt = select(
        func.coalesce(func.sum(Project.total_development_cost), 0).label("tdc"),
        func.coalesce(func.sum(Project.total_funding_committed), 0).label("tfc"),
        func.coalesce(func.sum(Project.funding_gap), 0).label("fg"),
        func.coalesce(func.sum(Project.debt_amount), 0).label("debt"),
        func.coalesce(func.sum(Project.equity_amount), 0).label("equity"),
        func.coalesce(func.sum(Project.subsidy_amount), 0).label("subsidy"),
    ).where(base_filter)
    r = db.execute(stmt).first()
    if r is None:
        return FundingSummary()
    return FundingSummary(
        total_development_cost=float(r.tdc),
        total_funding_committed=float(r.tfc),
        total_funding_gap=float(r.fg),
        total_debt=float(r.debt),
        total_equity=float(r.equity),
        total_subsidy=float(r.subsidy),
    )


def _build_velocity_metrics(db: Session, base_filter: Any) -> VelocityMetrics:
    """Compute pipeline velocity metrics."""
    stmt = select(
        func.avg(Project.concept_to_groundbreaking_days).label("avg_c2c"),
        func.avg(Project.entitlement_duration_days).label("avg_ent"),
        func.avg(Project.financing_duration_days).label("avg_fin"),
        func.avg(Project.construction_duration_days).label("avg_con"),
    ).where(base_filter)
    r = db.execute(stmt).first()

    twelve_months_ago = date.today().replace(
        year=date.today().year - 1,
    )
    completed_stmt = select(
        func.count(Project.project_id).label("cnt"),
        func.coalesce(func.sum(Project.total_units), 0).label("units"),
    ).where(
        base_filter,
        Project.current_stage == PipelineStage.OPERATIONS,
        Project.construction_complete >= twelve_months_ago,
    )
    comp = db.execute(completed_stmt).first()

    return VelocityMetrics(
        avg_concept_to_construction_days=round(float(r.avg_c2c), 1) if r and r.avg_c2c else None,
        avg_entitlement_days=round(float(r.avg_ent), 1) if r and r.avg_ent else None,
        avg_financing_days=round(float(r.avg_fin), 1) if r and r.avg_fin else None,
        avg_construction_days=round(float(r.avg_con), 1) if r and r.avg_con else None,
        projects_completed_last_12_months=comp.cnt if comp else 0,
        units_completed_last_12_months=int(comp.units) if comp else 0,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/overview",
    response_model=PortfolioOverview,
    summary="Get portfolio overview",
)
def get_portfolio_overview(
    db: DbSession,
    jurisdiction: str | None = Query(None, description="Filter by jurisdiction"),
    state: str | None = Query(None, max_length=2, description="Filter by state"),
    city: str | None = Query(None, description="Filter by city"),
    developer_org: str | None = Query(None, description="Filter by developer org"),
) -> PortfolioOverview:
    """Generate a real-time portfolio overview for the filtered set of projects.

    This endpoint computes headline metrics, stage and health distributions,
    aggregate funding, and pipeline velocity on the fly.  For frequently
    accessed slices consider creating a saved portfolio dashboard via
    ``POST /api/v1/portfolio/dashboards``.
    """
    # Build a composable boolean filter.
    conditions = [Project.project_id.isnot(None)]  # always-true seed
    if jurisdiction:
        conditions.append(Project.jurisdiction == jurisdiction)
    if state:
        conditions.append(Project.state == state.upper())
    if city:
        conditions.append(Project.city == city)
    if developer_org:
        conditions.append(Project.developer_org == developer_org)

    from sqlalchemy import and_
    base_filter = and_(*conditions)

    # Headline counts.
    totals_stmt = select(
        func.count(Project.project_id).label("total_projects"),
        func.coalesce(func.sum(Project.total_units), 0).label("total_units"),
        func.coalesce(func.sum(Project.affordable_units), 0).label("total_affordable"),
    ).where(base_filter)
    totals = db.execute(totals_stmt).first()

    stage_dist = _build_stage_distribution(db, base_filter)
    health_dist = _build_health_distribution(db, base_filter)
    funding = _build_funding_summary(db, base_filter)
    velocity = _build_velocity_metrics(db, base_filter)

    at_risk_stmt = select(func.count()).where(
        base_filter, Project.overall_health == OverallHealth.AT_RISK,
    )
    at_risk = db.scalar(at_risk_stmt) or 0

    stalled_stmt = select(func.count()).where(
        base_filter, Project.current_stage == PipelineStage.STALLED,
    )
    stalled = db.scalar(stalled_stmt) or 0

    portfolio_name_parts: list[str] = []
    if jurisdiction:
        portfolio_name_parts.append(jurisdiction)
    if city:
        portfolio_name_parts.append(city)
    if state:
        portfolio_name_parts.append(state.upper())
    portfolio_name = " / ".join(portfolio_name_parts) if portfolio_name_parts else "All Projects"

    return PortfolioOverview(
        generated_at=datetime.utcnow().isoformat(),
        portfolio_name=portfolio_name,
        jurisdiction=jurisdiction,
        state=state,
        total_projects=totals.total_projects if totals else 0,
        total_units=int(totals.total_units) if totals else 0,
        total_affordable_units=int(totals.total_affordable) if totals else 0,
        stage_distribution=stage_dist,
        health_distribution=health_dist,
        funding=funding,
        velocity=velocity,
        at_risk_projects=at_risk,
        stalled_projects=stalled,
    )


@router.get(
    "/dashboards",
    response_model=PortfolioDashboardListResponse,
    summary="List saved portfolio dashboards",
)
def list_dashboards(
    db: DbSession,
    pagination: PaginationDep,
    portfolio_type: PortfolioType | None = Query(None, description="Filter by portfolio type"),
    organization: str | None = Query(None, description="Filter by organization"),
    is_public: bool | None = Query(None, description="Filter by visibility"),
) -> PortfolioDashboardListResponse:
    """Return saved portfolio dashboard configurations.

    These are reusable, named filter sets that stakeholders create so they
    can quickly access their slice of the pipeline.
    """
    stmt = select(PortfolioDashboard)
    if portfolio_type is not None:
        stmt = stmt.where(PortfolioDashboard.portfolio_type == portfolio_type)
    if organization is not None:
        stmt = stmt.where(PortfolioDashboard.organization == organization)
    if is_public is not None:
        stmt = stmt.where(PortfolioDashboard.is_public == is_public)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0

    stmt = stmt.order_by(PortfolioDashboard.updated_at.desc())
    stmt = stmt.limit(pagination.limit).offset(pagination.offset)
    dashboards = list(db.scalars(stmt).all())

    return PortfolioDashboardListResponse(
        items=[PortfolioDashboardResponse.model_validate(d) for d in dashboards],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get(
    "/dashboards/{portfolio_id}",
    response_model=PortfolioDashboardResponse,
    summary="Get a saved portfolio dashboard",
)
def get_dashboard(
    portfolio_id: uuid.UUID,
    db: DbSession,
) -> PortfolioDashboardResponse:
    """Retrieve a single saved portfolio dashboard by ID."""
    dashboard = db.get(PortfolioDashboard, portfolio_id)
    if dashboard is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portfolio dashboard {portfolio_id} not found",
        )
    return PortfolioDashboardResponse.model_validate(dashboard)


@router.post(
    "/dashboards",
    response_model=PortfolioDashboardResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a saved portfolio dashboard",
)
def create_dashboard(
    payload: PortfolioDashboardCreate,
    db: DbSession,
) -> PortfolioDashboardResponse:
    """Create a new saved portfolio dashboard.

    The dashboard is a named filter configuration.  Cached aggregate metrics
    (total_projects, total_units, etc.) are computed and stored on creation
    and can be refreshed via ``POST /api/v1/portfolio/dashboards/{id}/refresh``.
    """
    dashboard = PortfolioDashboard(
        **payload.model_dump(exclude_unset=True),
    )

    # Compute initial cached metrics based on the geography filter.
    geo = payload.geography_filter or {}
    conditions = [Project.project_id.isnot(None)]
    if geo.get("jurisdiction"):
        conditions.append(Project.jurisdiction == geo["jurisdiction"])
    if geo.get("state"):
        conditions.append(Project.state == geo["state"])
    if geo.get("city"):
        conditions.append(Project.city == geo["city"])

    from sqlalchemy import and_
    base_filter = and_(*conditions)

    totals_stmt = select(
        func.count(Project.project_id).label("total_projects"),
        func.coalesce(func.sum(Project.total_units), 0).label("total_units"),
        func.coalesce(func.sum(Project.funding_gap), 0).label("funding_gap"),
    ).where(base_filter)
    totals = db.execute(totals_stmt).first()

    at_risk_stmt = select(func.count()).where(
        base_filter, Project.overall_health == OverallHealth.AT_RISK,
    )
    at_risk = db.scalar(at_risk_stmt) or 0

    dashboard.total_projects = totals.total_projects if totals else 0
    dashboard.total_units = int(totals.total_units) if totals else 0
    dashboard.funding_gap_aggregate = float(totals.funding_gap) if totals else 0
    dashboard.at_risk_count = at_risk
    dashboard.last_calculated = datetime.utcnow()

    db.add(dashboard)
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to create portfolio dashboard")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create portfolio dashboard",
        )

    db.refresh(dashboard)
    return PortfolioDashboardResponse.model_validate(dashboard)


@router.post(
    "/dashboards/{portfolio_id}/refresh",
    response_model=PortfolioDashboardResponse,
    summary="Refresh cached portfolio metrics",
)
def refresh_dashboard(
    portfolio_id: uuid.UUID,
    db: DbSession,
) -> PortfolioDashboardResponse:
    """Recompute the cached aggregate metrics for a saved dashboard.

    Uses the stored filter configuration to re-query the project table and
    update the cached totals.  Delegates to
    ``src.analytics.generate_portfolio_intelligence`` when available.
    """
    dashboard = db.get(PortfolioDashboard, portfolio_id)
    if dashboard is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portfolio dashboard {portfolio_id} not found",
        )

    # Try analytics module first.
    try:
        from src.analytics import generate_portfolio_intelligence
        result = generate_portfolio_intelligence(db, portfolio_id=portfolio_id)
        dashboard.total_projects = result.get("total_projects", dashboard.total_projects)
        dashboard.total_units = result.get("total_units", dashboard.total_units)
        dashboard.funding_gap_aggregate = result.get("funding_gap_aggregate", dashboard.funding_gap_aggregate)
        dashboard.at_risk_count = result.get("at_risk_count", dashboard.at_risk_count)
        dashboard.units_by_stage = result.get("units_by_stage")
        dashboard.velocity_metrics = result.get("velocity_metrics")
    except (ImportError, AttributeError):
        # Fallback: recompute from DB.
        geo = dashboard.geography_filter or {}
        conditions = [Project.project_id.isnot(None)]
        if geo.get("jurisdiction"):
            conditions.append(Project.jurisdiction == geo["jurisdiction"])
        if geo.get("state"):
            conditions.append(Project.state == geo["state"])
        if geo.get("city"):
            conditions.append(Project.city == geo["city"])

        from sqlalchemy import and_
        base_filter = and_(*conditions)

        totals_stmt = select(
            func.count(Project.project_id).label("total_projects"),
            func.coalesce(func.sum(Project.total_units), 0).label("total_units"),
            func.coalesce(func.sum(Project.funding_gap), 0).label("funding_gap"),
        ).where(base_filter)
        totals = db.execute(totals_stmt).first()

        at_risk_stmt = select(func.count()).where(
            base_filter, Project.overall_health == OverallHealth.AT_RISK,
        )

        dashboard.total_projects = totals.total_projects if totals else 0
        dashboard.total_units = int(totals.total_units) if totals else 0
        dashboard.funding_gap_aggregate = float(totals.funding_gap) if totals else 0
        dashboard.at_risk_count = db.scalar(at_risk_stmt) or 0

    dashboard.last_calculated = datetime.utcnow()
    dashboard.updated_at = datetime.utcnow()

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to refresh portfolio %s", portfolio_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to refresh portfolio metrics",
        )

    db.refresh(dashboard)
    return PortfolioDashboardResponse.model_validate(dashboard)
