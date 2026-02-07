"""Portfolio dashboard generation for stakeholders.

Aggregates project data across multiple dimensions (stage, geography,
funding status, health, timeline) to produce comprehensive portfolio
dashboards for PHAs, funders, cities, states, and researchers.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime
from typing import TypedDict
from uuid import UUID

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.analytics.health_assessment import (
    HealthAssessmentResult,
    assess_project_health,
)
from src.analytics.peer_benchmarking import _load_national_benchmarks
from src.analytics.timeline_prediction import (
    TimelinePredictionResult,
    predict_project_timeline,
)
from src.database.queries import (
    get_portfolio_summary_stats,
    get_stage_distribution,
    get_stalled_projects,
    query_projects,
)
from src.models.enums import (
    FundingSourceStatus,
    FundingSourceType,
    OverallHealth,
    PipelineStage,
    PortfolioType,
    StakeholderType,
)
from src.models.funding_source import FundingSource
from src.models.portfolio import PortfolioDashboard
from src.models.project import Project

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed results
# ---------------------------------------------------------------------------


class StageDistribution(TypedDict):
    """Project and unit counts by pipeline stage."""

    stage: str
    project_count: int
    total_units: int
    affordable_units: int
    median_days_in_stage: float | None


class HealthDistribution(TypedDict):
    """Project counts by health status."""

    health_status: str
    project_count: int
    total_units: int
    percentage: float


class FundingBreakdown(TypedDict):
    """Funding aggregation by source type."""

    source_type: str
    total_amount: float
    source_count: int
    committed_amount: float
    gap_amount: float


class VelocityMetrics(TypedDict):
    """Pipeline velocity measurements."""

    projects_entering_pipeline_last_90d: int
    projects_completing_last_90d: int
    median_concept_to_construction_days: float | None
    median_concept_to_co_days: float | None
    throughput_units_per_month: float
    stage_velocity: dict[str, float]  # stage -> median days


class GeographicBreakdown(TypedDict):
    """Aggregation by geographic area."""

    area: str
    area_type: str  # "city", "county", "jurisdiction"
    project_count: int
    total_units: int
    at_risk_count: int
    average_health_score: float


class AtRiskSummary(TypedDict):
    """Summary of at-risk and stalled projects."""

    project_id: str
    project_name: str
    current_stage: str
    days_in_stage: int | None
    health_score: float | None
    primary_risk: str | None
    funding_gap: float | None


class PortfolioDashboardResult(TypedDict):
    """Complete portfolio intelligence dashboard."""

    portfolio_id: str | None
    portfolio_name: str
    stakeholder_type: str
    generated_at: str

    # Summary
    total_projects: int
    total_units: int
    total_affordable_units: int
    total_development_cost: float
    total_funding_gap: float

    # Distributions
    stage_distribution: list[StageDistribution]
    health_distribution: list[HealthDistribution]
    funding_breakdown: list[FundingBreakdown]
    geographic_breakdown: list[GeographicBreakdown]

    # Velocity
    velocity: VelocityMetrics

    # At-risk
    at_risk_projects: list[AtRiskSummary]
    stalled_projects: list[AtRiskSummary]

    # Timeline outlook
    projects_expected_co_next_12m: int
    units_expected_co_next_12m: int
    projects_expected_groundbreaking_next_6m: int

    # Key metrics
    average_health_score: float
    median_cost_per_unit: float | None
    average_friction_score: float | None


# ---------------------------------------------------------------------------
# Dashboard generation
# ---------------------------------------------------------------------------


def generate_portfolio_dashboard(
    db: Session,
    *,
    portfolio_id: UUID | None = None,
    jurisdiction: str | None = None,
    city: str | None = None,
    state: str | None = None,
    stakeholder_type: StakeholderType = StakeholderType.CITY,
    funding_organization: str | None = None,
    limit: int = 1000,
) -> PortfolioDashboardResult:
    """Generate a comprehensive portfolio intelligence dashboard.

    Aggregates project data across multiple dimensions to produce a
    stakeholder-appropriate view of the housing pipeline.

    Args:
        db: SQLAlchemy session.
        portfolio_id: Optional saved PortfolioDashboard to use for filters.
        jurisdiction: Optional jurisdiction filter.
        city: Optional city filter.
        state: Optional state filter.
        stakeholder_type: Type of stakeholder viewing the dashboard.
        funding_organization: Filter to projects funded by this org.
        limit: Maximum projects to include.

    Returns:
        PortfolioDashboardResult with full dashboard data.
    """
    # Load portfolio filters if portfolio_id provided
    portfolio_name = "Ad-hoc Dashboard"
    if portfolio_id:
        portfolio = db.get(PortfolioDashboard, portfolio_id)
        if portfolio:
            portfolio_name = portfolio.portfolio_name
            # Apply stored filters
            if portfolio.geography_filter:
                jurisdiction = jurisdiction or portfolio.geography_filter.get("jurisdiction")
                city = city or portfolio.geography_filter.get("city")
                state = state or portfolio.geography_filter.get("state")

    # Fetch projects
    projects = query_projects(
        db,
        jurisdiction=jurisdiction,
        city=city,
        state=state,
        funding_source_organization=funding_organization,
        limit=limit,
    )

    if not projects:
        return _empty_dashboard(
            portfolio_id, portfolio_name, stakeholder_type
        )

    # Summary stats
    summary = get_portfolio_summary_stats(
        db, jurisdiction=jurisdiction, city=city, state=state
    )

    # Stage distribution
    stage_dist = _compute_stage_distribution(projects)

    # Health distribution
    health_dist = _compute_health_distribution(projects)

    # Funding breakdown
    funding_bkdn = _compute_funding_breakdown(db, projects)

    # Geographic breakdown
    geo_bkdn = _compute_geographic_breakdown(projects)

    # Velocity metrics
    velocity = _compute_velocity_metrics(db, projects, jurisdiction)

    # At-risk & stalled
    at_risk = _identify_at_risk_projects(projects)
    stalled = _identify_stalled_projects(db, jurisdiction, state)

    # Timeline outlook
    co_12m, units_12m = _projects_expected_co(projects, months=12)
    gb_6m = _projects_expected_groundbreaking(projects, months=6)

    # Aggregate scores
    health_scores = [
        p.health_score for p in projects if p.health_score is not None
    ]
    avg_health = float(np.mean(health_scores)) if health_scores else 0.0

    cpus = [
        float(p.cost_per_unit)
        for p in projects
        if p.cost_per_unit is not None
    ]
    median_cpu = float(np.median(cpus)) if cpus else None

    friction_scores = [
        p.jurisdiction_friction_score
        for p in projects
        if p.jurisdiction_friction_score is not None
    ]
    avg_friction = float(np.mean(friction_scores)) if friction_scores else None

    return PortfolioDashboardResult(
        portfolio_id=str(portfolio_id) if portfolio_id else None,
        portfolio_name=portfolio_name,
        stakeholder_type=stakeholder_type.value,
        generated_at=datetime.utcnow().isoformat(),
        total_projects=summary["total_projects"],
        total_units=summary["total_units"],
        total_affordable_units=summary["total_affordable_units"],
        total_development_cost=summary["total_cost"],
        total_funding_gap=summary["total_funding_gap"],
        stage_distribution=stage_dist,
        health_distribution=health_dist,
        funding_breakdown=funding_bkdn,
        geographic_breakdown=geo_bkdn,
        velocity=velocity,
        at_risk_projects=at_risk,
        stalled_projects=stalled,
        projects_expected_co_next_12m=co_12m,
        units_expected_co_next_12m=units_12m,
        projects_expected_groundbreaking_next_6m=gb_6m,
        average_health_score=round(avg_health, 1),
        median_cost_per_unit=round(median_cpu, 2) if median_cpu else None,
        average_friction_score=round(avg_friction, 1) if avg_friction else None,
    )


def generate_and_persist_dashboard(
    db: Session,
    portfolio_id: UUID,
    **kwargs,
) -> PortfolioDashboardResult:
    """Generate dashboard and cache results to the PortfolioDashboard record.

    Args:
        db: SQLAlchemy session.
        portfolio_id: UUID of the PortfolioDashboard to update.
        **kwargs: Additional arguments for generate_portfolio_dashboard.

    Returns:
        PortfolioDashboardResult.

    Raises:
        ValueError: If the portfolio is not found.
    """
    dashboard = generate_portfolio_dashboard(
        db, portfolio_id=portfolio_id, **kwargs
    )

    portfolio = db.get(PortfolioDashboard, portfolio_id)
    if portfolio is None:
        raise ValueError(f"PortfolioDashboard {portfolio_id} not found.")

    portfolio.total_projects = dashboard["total_projects"]
    portfolio.total_units = dashboard["total_units"]
    portfolio.units_by_stage = {
        sd["stage"]: sd["total_units"] for sd in dashboard["stage_distribution"]
    }
    portfolio.funding_gap_aggregate = dashboard["total_funding_gap"]
    portfolio.at_risk_count = len(dashboard["at_risk_projects"])
    portfolio.velocity_metrics = {
        "throughput_units_per_month": dashboard["velocity"]["throughput_units_per_month"],
        "projects_entering_90d": dashboard["velocity"]["projects_entering_pipeline_last_90d"],
        "projects_completing_90d": dashboard["velocity"]["projects_completing_last_90d"],
    }
    portfolio.last_calculated = datetime.utcnow()

    db.commit()
    logger.info(
        "Persisted dashboard metrics for portfolio %s.",
        portfolio_id,
    )

    return dashboard


# ---------------------------------------------------------------------------
# Stakeholder-specific views
# ---------------------------------------------------------------------------


def generate_funder_view(
    db: Session,
    funding_organization: str,
    *,
    state: str | None = None,
) -> PortfolioDashboardResult:
    """Generate a funder-specific portfolio view.

    Filters to projects where the organization is a funding source.

    Args:
        db: SQLAlchemy session.
        funding_organization: Name of the funding organization.
        state: Optional state filter.

    Returns:
        PortfolioDashboardResult scoped to the funder's portfolio.
    """
    return generate_portfolio_dashboard(
        db,
        state=state,
        stakeholder_type=StakeholderType.FUNDER,
        funding_organization=funding_organization,
    )


def generate_pha_view(
    db: Session,
    jurisdiction: str,
) -> PortfolioDashboardResult:
    """Generate a PHA (Public Housing Authority) view.

    Args:
        db: SQLAlchemy session.
        jurisdiction: PHA service area jurisdiction.

    Returns:
        PortfolioDashboardResult scoped to the PHA's jurisdiction.
    """
    return generate_portfolio_dashboard(
        db,
        jurisdiction=jurisdiction,
        stakeholder_type=StakeholderType.PHA,
    )


def generate_state_view(
    db: Session,
    state: str,
) -> PortfolioDashboardResult:
    """Generate a state-level portfolio view.

    Args:
        db: SQLAlchemy session.
        state: Two-letter state code.

    Returns:
        PortfolioDashboardResult aggregated at the state level.
    """
    return generate_portfolio_dashboard(
        db,
        state=state,
        stakeholder_type=StakeholderType.STATE,
    )


# ---------------------------------------------------------------------------
# Internal aggregation helpers
# ---------------------------------------------------------------------------


def _compute_stage_distribution(
    projects: list[Project],
) -> list[StageDistribution]:
    """Compute project and unit counts grouped by pipeline stage."""
    by_stage: dict[str, dict] = defaultdict(
        lambda: {
            "count": 0,
            "units": 0,
            "affordable": 0,
            "days": [],
        }
    )

    for p in projects:
        stage = p.current_stage.value
        by_stage[stage]["count"] += 1
        by_stage[stage]["units"] += p.total_units or 0
        by_stage[stage]["affordable"] += p.affordable_units or 0
        if p.days_in_current_stage is not None:
            by_stage[stage]["days"].append(p.days_in_current_stage)

    result: list[StageDistribution] = []
    for stage_val in PipelineStage:
        stage = stage_val.value
        data = by_stage.get(stage)
        if data and data["count"] > 0:
            days_arr = data["days"]
            median_days = (
                float(np.median(days_arr)) if days_arr else None
            )
            result.append(
                StageDistribution(
                    stage=stage,
                    project_count=data["count"],
                    total_units=data["units"],
                    affordable_units=data["affordable"],
                    median_days_in_stage=median_days,
                )
            )

    return result


def _compute_health_distribution(
    projects: list[Project],
) -> list[HealthDistribution]:
    """Compute project counts grouped by health status."""
    by_health: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "units": 0}
    )

    for p in projects:
        health = (
            p.overall_health.value
            if p.overall_health
            else "unknown"
        )
        by_health[health]["count"] += 1
        by_health[health]["units"] += p.total_units or 0

    total = len(projects) or 1
    result: list[HealthDistribution] = []

    for health_val in list(OverallHealth) + [None]:
        key = health_val.value if health_val else "unknown"
        data = by_health.get(key)
        if data and data["count"] > 0:
            result.append(
                HealthDistribution(
                    health_status=key,
                    project_count=data["count"],
                    total_units=data["units"],
                    percentage=round(data["count"] / total * 100, 1),
                )
            )

    return result


def _compute_funding_breakdown(
    db: Session,
    projects: list[Project],
) -> list[FundingBreakdown]:
    """Aggregate funding by source type across portfolio projects."""
    project_ids = [p.project_id for p in projects]
    if not project_ids:
        return []

    stmt = select(FundingSource).where(
        FundingSource.project_id.in_(project_ids)
    )
    sources = list(db.scalars(stmt).all())

    by_type: dict[str, dict] = defaultdict(
        lambda: {
            "total": 0.0,
            "count": 0,
            "committed": 0.0,
        }
    )

    committed_statuses = {
        FundingSourceStatus.AWARDED,
        FundingSourceStatus.COMMITTED,
        FundingSourceStatus.CLOSED,
    }

    for s in sources:
        key = s.source_type.value
        amount = float(s.amount or 0)
        by_type[key]["total"] += amount
        by_type[key]["count"] += 1
        if s.status in committed_statuses:
            by_type[key]["committed"] += amount

    result: list[FundingBreakdown] = []
    for src_type, data in sorted(
        by_type.items(), key=lambda x: x[1]["total"], reverse=True
    ):
        result.append(
            FundingBreakdown(
                source_type=src_type,
                total_amount=round(data["total"], 2),
                source_count=data["count"],
                committed_amount=round(data["committed"], 2),
                gap_amount=round(data["total"] - data["committed"], 2),
            )
        )

    return result


def _compute_geographic_breakdown(
    projects: list[Project],
) -> list[GeographicBreakdown]:
    """Aggregate projects by jurisdiction/city."""
    by_area: dict[str, dict] = defaultdict(
        lambda: {
            "type": "jurisdiction",
            "count": 0,
            "units": 0,
            "at_risk": 0,
            "scores": [],
        }
    )

    for p in projects:
        area = p.jurisdiction or p.city or p.county or "unknown"
        area_type = "jurisdiction" if p.jurisdiction else "city"
        by_area[area]["type"] = area_type
        by_area[area]["count"] += 1
        by_area[area]["units"] += p.total_units or 0
        if p.overall_health in (OverallHealth.AT_RISK, OverallHealth.DELAYED, OverallHealth.STALLED):
            by_area[area]["at_risk"] += 1
        if p.health_score is not None:
            by_area[area]["scores"].append(float(p.health_score))

    result: list[GeographicBreakdown] = []
    for area, data in sorted(
        by_area.items(), key=lambda x: x[1]["count"], reverse=True
    ):
        scores = data["scores"]
        avg_score = float(np.mean(scores)) if scores else 0.0
        result.append(
            GeographicBreakdown(
                area=area,
                area_type=data["type"],
                project_count=data["count"],
                total_units=data["units"],
                at_risk_count=data["at_risk"],
                average_health_score=round(avg_score, 1),
            )
        )

    return result


def _compute_velocity_metrics(
    db: Session,
    projects: list[Project],
    jurisdiction: str | None,
) -> VelocityMetrics:
    """Compute pipeline throughput and stage velocity metrics."""
    today = date.today()
    ninety_days_ago = today - __import__("datetime").timedelta(days=90)

    # Projects entering pipeline in last 90 days
    entering = sum(
        1
        for p in projects
        if p.created_at and p.created_at.date() >= ninety_days_ago
    )

    # Projects completing (reaching operations/lease_up) in last 90 days
    completing = sum(
        1
        for p in projects
        if p.current_stage in (PipelineStage.OPERATIONS, PipelineStage.LEASE_UP)
        and p.stage_entry_date
        and p.stage_entry_date >= ninety_days_ago
    )

    # Concept to construction duration
    c2c_durations = [
        p.concept_to_groundbreaking_days
        for p in projects
        if p.concept_to_groundbreaking_days is not None
    ]
    median_c2c = float(np.median(c2c_durations)) if c2c_durations else None

    # Concept to CO
    c2co_durations = [
        p.concept_to_co_days
        for p in projects
        if p.concept_to_co_days is not None
    ]
    median_c2co = float(np.median(c2co_durations)) if c2co_durations else None

    # Throughput: units reaching operations per month (last 12 months)
    twelve_months_ago = today - __import__("datetime").timedelta(days=365)
    completed_units = sum(
        p.total_units or 0
        for p in projects
        if p.current_stage == PipelineStage.OPERATIONS
        and p.stage_entry_date
        and p.stage_entry_date >= twelve_months_ago
    )
    throughput = completed_units / 12.0

    # Per-stage velocity (median days for completed stages)
    stage_velocity: dict[str, float] = {}
    for stage_name in [
        "concept",
        "pre_development",
        "entitlement",
        "financing",
        "construction",
        "lease_up",
    ]:
        attr = f"{stage_name}_duration_days"
        durations = [
            float(getattr(p, attr))
            for p in projects
            if getattr(p, attr, None) is not None
        ]
        if durations:
            stage_velocity[stage_name] = float(np.median(durations))

    return VelocityMetrics(
        projects_entering_pipeline_last_90d=entering,
        projects_completing_last_90d=completing,
        median_concept_to_construction_days=median_c2c,
        median_concept_to_co_days=median_c2co,
        throughput_units_per_month=round(throughput, 1),
        stage_velocity=stage_velocity,
    )


def _identify_at_risk_projects(
    projects: list[Project],
) -> list[AtRiskSummary]:
    """Identify projects with at_risk, delayed, or stalled health."""
    at_risk_statuses = {
        OverallHealth.AT_RISK,
        OverallHealth.DELAYED,
        OverallHealth.STALLED,
    }

    results: list[AtRiskSummary] = []
    for p in projects:
        if p.overall_health in at_risk_statuses:
            # Determine primary risk from risk_factors JSON
            primary_risk = None
            if p.risk_factors and isinstance(p.risk_factors, dict):
                # Pick the highest-scored risk factor
                try:
                    primary_risk = max(
                        p.risk_factors.keys(),
                        key=lambda k: p.risk_factors[k]
                        if isinstance(p.risk_factors[k], (int, float))
                        else 0,
                    )
                except (ValueError, TypeError):
                    primary_risk = None

            results.append(
                AtRiskSummary(
                    project_id=str(p.project_id),
                    project_name=p.project_name,
                    current_stage=p.current_stage.value,
                    days_in_stage=p.days_in_current_stage,
                    health_score=float(p.health_score) if p.health_score else None,
                    primary_risk=primary_risk,
                    funding_gap=(
                        float(p.funding_gap) if p.funding_gap else None
                    ),
                )
            )

    # Sort by health score ascending (worst first)
    results.sort(key=lambda r: r["health_score"] or 0)
    return results


def _identify_stalled_projects(
    db: Session,
    jurisdiction: str | None,
    state: str | None,
) -> list[AtRiskSummary]:
    """Find projects that appear stalled based on time in stage."""
    stalled = get_stalled_projects(
        db, days_threshold=180, jurisdiction=jurisdiction
    )

    results: list[AtRiskSummary] = []
    for p in stalled:
        if state and p.state != state:
            continue
        results.append(
            AtRiskSummary(
                project_id=str(p.project_id),
                project_name=p.project_name,
                current_stage=p.current_stage.value,
                days_in_stage=p.days_in_current_stage,
                health_score=float(p.health_score) if p.health_score else None,
                primary_risk="stalled_in_stage",
                funding_gap=(
                    float(p.funding_gap) if p.funding_gap else None
                ),
            )
        )

    results.sort(key=lambda r: -(r["days_in_stage"] or 0))
    return results


def _projects_expected_co(
    projects: list[Project],
    months: int = 12,
) -> tuple[int, int]:
    """Count projects with predicted CO within the given timeframe."""
    cutoff = date.today() + __import__("datetime").timedelta(days=months * 30)
    count = 0
    units = 0
    for p in projects:
        if p.predicted_co and p.predicted_co <= cutoff:
            count += 1
            units += p.total_units or 0
    return count, units


def _projects_expected_groundbreaking(
    projects: list[Project],
    months: int = 6,
) -> int:
    """Count projects with predicted groundbreaking within the timeframe."""
    cutoff = date.today() + __import__("datetime").timedelta(days=months * 30)
    return sum(
        1
        for p in projects
        if p.predicted_groundbreaking and p.predicted_groundbreaking <= cutoff
    )


def _empty_dashboard(
    portfolio_id: UUID | None,
    portfolio_name: str,
    stakeholder_type: StakeholderType,
) -> PortfolioDashboardResult:
    """Return an empty dashboard when no projects match."""
    return PortfolioDashboardResult(
        portfolio_id=str(portfolio_id) if portfolio_id else None,
        portfolio_name=portfolio_name,
        stakeholder_type=stakeholder_type.value,
        generated_at=datetime.utcnow().isoformat(),
        total_projects=0,
        total_units=0,
        total_affordable_units=0,
        total_development_cost=0.0,
        total_funding_gap=0.0,
        stage_distribution=[],
        health_distribution=[],
        funding_breakdown=[],
        geographic_breakdown=[],
        velocity=VelocityMetrics(
            projects_entering_pipeline_last_90d=0,
            projects_completing_last_90d=0,
            median_concept_to_construction_days=None,
            median_concept_to_co_days=None,
            throughput_units_per_month=0.0,
            stage_velocity={},
        ),
        at_risk_projects=[],
        stalled_projects=[],
        projects_expected_co_next_12m=0,
        units_expected_co_next_12m=0,
        projects_expected_groundbreaking_next_6m=0,
        average_health_score=0.0,
        median_cost_per_unit=None,
        average_friction_score=None,
    )
