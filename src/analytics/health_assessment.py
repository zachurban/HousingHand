"""Pipeline health assessment with weighted scoring.

Computes a composite health score for each project based on five
dimensions: timeline adherence (30%), budget variance (25%),
funding completeness (20%), risk exposure (15%), and team stability
(10%). Scores map to OverallHealth categories (on_track, at_risk,
delayed, stalled) using configurable thresholds from national
benchmarks.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TypedDict
from uuid import UUID

import numpy as np
import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.analytics.peer_benchmarking import (
    PeerBenchmarkResult,
    compute_peer_benchmarks,
    _load_national_benchmarks,
)
from src.database.queries import get_project, query_projects
from src.models.enums import (
    FundingSourceStatus,
    OverallHealth,
    PipelineStage,
)
from src.models.funding_source import FundingSource
from src.models.project import Project

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Weight configuration
# ---------------------------------------------------------------------------

HEALTH_WEIGHTS: dict[str, float] = {
    "timeline": 0.30,
    "budget": 0.25,
    "funding": 0.20,
    "risk": 0.15,
    "team": 0.10,
}

# Stages considered terminal (not scored)
_TERMINAL_STAGES = {PipelineStage.OPERATIONS, PipelineStage.ABANDONED}

# Stages that can be assessed
_ACTIVE_STAGES_LIST = [
    "concept",
    "pre_development",
    "entitlement",
    "financing",
    "construction",
    "lease_up",
]


# ---------------------------------------------------------------------------
# Typed results
# ---------------------------------------------------------------------------


class DimensionScore(TypedDict):
    """Score for a single health dimension."""

    dimension: str
    raw_score: float  # 0-100
    weight: float
    weighted_score: float
    detail: str


class HealthAssessmentResult(TypedDict):
    """Complete health assessment for one project."""

    project_id: str
    project_name: str
    current_stage: str
    composite_score: float  # 0-100
    overall_health: str  # OverallHealth enum value
    dimensions: dict[str, DimensionScore]
    previous_score: float | None
    score_trend: str  # "improving", "stable", "declining"
    recommendations: list[str]
    assessed_at: str


class BatchHealthResult(TypedDict):
    """Summary of batch health assessment across multiple projects."""

    total_assessed: int
    health_distribution: dict[str, int]  # OverallHealth -> count
    average_score: float
    median_score: float
    projects_declining: int
    projects_improving: int
    assessments: list[HealthAssessmentResult]
    assessed_at: str


# ---------------------------------------------------------------------------
# Single project assessment
# ---------------------------------------------------------------------------


def assess_project_health(
    db: Session,
    project_id: UUID,
    peer_benchmark: PeerBenchmarkResult | None = None,
) -> HealthAssessmentResult:
    """Compute a weighted health score for a single project.

    Evaluates five dimensions and produces a composite score from 0 to 100.
    The score maps to an OverallHealth enum using configured thresholds.

    Args:
        db: SQLAlchemy session.
        project_id: UUID of the project to assess.
        peer_benchmark: Optional pre-computed peer benchmarks. If None,
            they will be computed from the project's jurisdiction and
            characteristics.

    Returns:
        HealthAssessmentResult with composite score, per-dimension
        breakdown, and actionable recommendations.

    Raises:
        ValueError: If the project is not found.
    """
    project = get_project(db, project_id)
    if project is None:
        raise ValueError(f"Project {project_id} not found.")

    if project.current_stage in _TERMINAL_STAGES:
        return _terminal_assessment(project)

    if peer_benchmark is None:
        peer_benchmark = compute_peer_benchmarks(
            db,
            jurisdiction=project.jurisdiction,
            state=project.state,
            building_type=(
                project.building_type.value if project.building_type else None
            ),
        )

    # Compute each dimension
    timeline_dim = _score_timeline(project, peer_benchmark)
    budget_dim = _score_budget(project)
    funding_dim = _score_funding(db, project)
    risk_dim = _score_risk(project)
    team_dim = _score_team(project)

    dimensions = {
        "timeline": timeline_dim,
        "budget": budget_dim,
        "funding": funding_dim,
        "risk": risk_dim,
        "team": team_dim,
    }

    # Weighted composite
    composite = sum(d["weighted_score"] for d in dimensions.values())
    composite = max(0.0, min(100.0, composite))

    # Map to health category
    overall = _score_to_health(composite)

    # Score trend (compare to stored score)
    previous = project.health_score
    if previous is not None:
        delta = composite - previous
        if delta > 3.0:
            trend = "improving"
        elif delta < -3.0:
            trend = "declining"
        else:
            trend = "stable"
    else:
        trend = "stable"

    # Generate recommendations
    recommendations = _generate_recommendations(project, dimensions, overall)

    return HealthAssessmentResult(
        project_id=str(project.project_id),
        project_name=project.project_name,
        current_stage=project.current_stage.value,
        composite_score=round(composite, 1),
        overall_health=overall.value,
        dimensions=dimensions,
        previous_score=float(previous) if previous is not None else None,
        score_trend=trend,
        recommendations=recommendations,
        assessed_at=datetime.utcnow().isoformat(),
    )


def assess_project_health_and_persist(
    db: Session,
    project_id: UUID,
    peer_benchmark: PeerBenchmarkResult | None = None,
) -> HealthAssessmentResult:
    """Assess health and write the score back to the project record.

    Args:
        db: SQLAlchemy session.
        project_id: UUID of the project to assess.
        peer_benchmark: Optional pre-computed peer benchmarks.

    Returns:
        HealthAssessmentResult (same as assess_project_health).
    """
    result = assess_project_health(db, project_id, peer_benchmark)

    project = get_project(db, project_id)
    if project:
        project.health_score = result["composite_score"]
        project.overall_health = OverallHealth(result["overall_health"])
        db.commit()
        logger.info(
            "Persisted health score %.1f (%s) for project %s.",
            result["composite_score"],
            result["overall_health"],
            project_id,
        )

    return result


# ---------------------------------------------------------------------------
# Batch assessment
# ---------------------------------------------------------------------------


def assess_batch_health(
    db: Session,
    *,
    jurisdiction: str | None = None,
    state: str | None = None,
    stages: list[PipelineStage] | None = None,
    limit: int = 500,
) -> BatchHealthResult:
    """Assess health for all projects matching filter criteria.

    Args:
        db: SQLAlchemy session.
        jurisdiction: Optional jurisdiction filter.
        state: Optional state filter.
        stages: Optional list of stages to include.
        limit: Maximum projects to assess.

    Returns:
        BatchHealthResult with distribution stats and all individual
        assessments.
    """
    active_stages = stages or [
        s
        for s in PipelineStage
        if s not in _TERMINAL_STAGES
    ]

    projects = query_projects(
        db,
        jurisdiction=jurisdiction,
        state=state,
        stages=active_stages,
        limit=limit,
    )

    # Pre-compute peer benchmarks once for the jurisdiction
    peer_benchmark = None
    if jurisdiction or state:
        peer_benchmark = compute_peer_benchmarks(
            db,
            jurisdiction=jurisdiction,
            state=state,
        )

    assessments: list[HealthAssessmentResult] = []
    health_counts: dict[str, int] = {h.value: 0 for h in OverallHealth}
    scores: list[float] = []
    improving = 0
    declining = 0

    for project in projects:
        try:
            result = assess_project_health(
                db, project.project_id, peer_benchmark
            )
            assessments.append(result)
            health_counts[result["overall_health"]] = (
                health_counts.get(result["overall_health"], 0) + 1
            )
            scores.append(result["composite_score"])

            if result["score_trend"] == "improving":
                improving += 1
            elif result["score_trend"] == "declining":
                declining += 1
        except Exception:
            logger.exception(
                "Failed to assess project %s.", project.project_id
            )

    score_arr = np.array(scores) if scores else np.array([0.0])

    return BatchHealthResult(
        total_assessed=len(assessments),
        health_distribution=health_counts,
        average_score=float(np.mean(score_arr)),
        median_score=float(np.median(score_arr)),
        projects_declining=declining,
        projects_improving=improving,
        assessments=assessments,
        assessed_at=datetime.utcnow().isoformat(),
    )


# ---------------------------------------------------------------------------
# Dimension scoring functions (0-100 each)
# ---------------------------------------------------------------------------


def _score_timeline(
    project: Project,
    peer_benchmark: PeerBenchmarkResult,
) -> DimensionScore:
    """Score timeline adherence by comparing actual days to peer medians.

    100 = at or below peer median for current stage.
    Linearly penalized for every percent over the median, reaching 0
    when actual >= 2x the peer median.
    """
    stage = project.current_stage.value
    days = project.days_in_current_stage

    if stage in ("operations", "abandoned", "stalled") or days is None:
        raw = 50.0
        detail = "No timeline data for scoring."
    else:
        bench = peer_benchmark["stage_benchmarks"].get(stage)
        if bench and bench["median_days"] > 0:
            ratio = days / bench["median_days"]
            if ratio <= 1.0:
                raw = 100.0
            elif ratio >= 2.0:
                raw = 0.0
            else:
                # Linear interpolation: 100 at ratio=1.0, 0 at ratio=2.0
                raw = max(0.0, 100.0 * (2.0 - ratio))

            detail = (
                f"Stage {stage}: {days}d actual vs "
                f"{bench['median_days']:.0f}d peer median "
                f"(ratio {ratio:.2f})"
            )
        else:
            raw = 70.0
            detail = f"No peer benchmark for stage {stage}; default score."

    weight = HEALTH_WEIGHTS["timeline"]
    return DimensionScore(
        dimension="timeline",
        raw_score=round(raw, 1),
        weight=weight,
        weighted_score=round(raw * weight, 2),
        detail=detail,
    )


def _score_budget(project: Project) -> DimensionScore:
    """Score budget health based on variance percentage.

    100 = variance <= 0% (on or under budget).
    Linearly deducted, reaching 0 at >= 30% over budget.
    """
    variance_pct = project.budget_variance_percent

    if variance_pct is None:
        # Check if we can compute from original / current budget
        if project.original_budget and project.current_budget:
            if float(project.original_budget) > 0:
                variance_pct = (
                    (float(project.current_budget) - float(project.original_budget))
                    / float(project.original_budget)
                    * 100.0
                )
            else:
                variance_pct = None

    if variance_pct is None:
        raw = 70.0
        detail = "No budget data available; default score."
    elif variance_pct <= 0:
        raw = 100.0
        detail = f"Budget variance {variance_pct:.1f}% (on/under budget)."
    elif variance_pct >= 30:
        raw = 0.0
        detail = f"Budget variance {variance_pct:.1f}% (severely over budget)."
    else:
        raw = max(0.0, 100.0 * (1.0 - variance_pct / 30.0))
        detail = f"Budget variance {variance_pct:.1f}%."

    weight = HEALTH_WEIGHTS["budget"]
    return DimensionScore(
        dimension="budget",
        raw_score=round(raw, 1),
        weight=weight,
        weighted_score=round(raw * weight, 2),
        detail=detail,
    )


def _score_funding(db: Session, project: Project) -> DimensionScore:
    """Score funding completeness based on committed/closed sources.

    100 = full funding stack committed or closed with no gap.
    Penalized proportionally to the funding gap as a fraction of TDC.
    """
    # Get funding sources
    stmt = select(FundingSource).where(
        FundingSource.project_id == project.project_id
    )
    sources = list(db.scalars(stmt).all())

    if not sources and project.funding_gap is None:
        raw = 50.0
        detail = "No funding sources recorded."
    else:
        committed_statuses = {
            FundingSourceStatus.AWARDED,
            FundingSourceStatus.COMMITTED,
            FundingSourceStatus.CLOSED,
        }
        total_committed = sum(
            float(s.amount or 0)
            for s in sources
            if s.status in committed_statuses
        )
        total_all = sum(float(s.amount or 0) for s in sources)

        tdc = float(project.total_development_cost or 0)
        gap = float(project.funding_gap or 0)

        if tdc > 0:
            # Percentage of TDC covered by committed sources
            committed_pct = (total_committed / tdc) * 100.0
            gap_pct = (gap / tdc) * 100.0 if gap > 0 else 0.0

            # Score: 100 at 100% committed, linearly down
            raw = min(100.0, committed_pct)
            # Additional penalty for explicit gap
            if gap_pct > 0:
                gap_penalty = min(30.0, gap_pct * 0.5)
                raw = max(0.0, raw - gap_penalty)

            detail = (
                f"${total_committed:,.0f} committed of ${tdc:,.0f} TDC "
                f"({committed_pct:.0f}%); gap ${gap:,.0f}."
            )
        elif total_all > 0:
            # No TDC but have sources - use ratio of committed to total
            ratio = total_committed / total_all if total_all > 0 else 0
            raw = ratio * 100.0
            detail = f"${total_committed:,.0f} of ${total_all:,.0f} committed."
        else:
            raw = 30.0
            detail = "Funding sources present but amounts not populated."

    weight = HEALTH_WEIGHTS["funding"]
    return DimensionScore(
        dimension="funding",
        raw_score=round(raw, 1),
        weight=weight,
        weighted_score=round(raw * weight, 2),
        detail=detail,
    )


def _score_risk(project: Project) -> DimensionScore:
    """Score risk exposure from risk_score, friction, and opposition.

    Combines the project's risk_score (0-100 where high = more risk),
    friction score, neighbor opposition, and appeals into a composite
    risk penalty.
    """
    penalties: list[float] = []

    # Risk score (inverse: high risk_score = low health)
    if project.risk_score is not None:
        penalties.append(project.risk_score)  # 0-100

    # Friction score (1-100 scale, higher = worse)
    if project.jurisdiction_friction_score is not None:
        penalties.append(min(100.0, project.jurisdiction_friction_score))

    # Neighbor opposition
    opposition_map = {
        "none": 0,
        "low": 15,
        "moderate": 35,
        "high": 60,
        "severe": 85,
    }
    if project.neighbor_opposition_level is not None:
        opp_val = opposition_map.get(project.neighbor_opposition_level.value, 0)
        penalties.append(float(opp_val))

    # Appeals filed
    if project.appeals_filed and project.appeals_filed > 0:
        penalties.append(min(100.0, project.appeals_filed * 25.0))

    if penalties:
        avg_penalty = np.mean(penalties)
        raw = max(0.0, 100.0 - avg_penalty)
        detail = (
            f"Average risk penalty {avg_penalty:.0f} from "
            f"{len(penalties)} risk factors."
        )
    else:
        raw = 75.0
        detail = "No explicit risk data; default score."

    weight = HEALTH_WEIGHTS["risk"]
    return DimensionScore(
        dimension="risk",
        raw_score=round(raw, 1),
        weight=weight,
        weighted_score=round(raw * weight, 2),
        detail=detail,
    )


def _score_team(project: Project) -> DimensionScore:
    """Score team completeness based on development team fields populated.

    Checks developer_org, architect, general_contractor, and
    property_manager. Each present field adds 25 points.
    """
    team_fields = [
        project.developer_org,
        project.architect,
        project.general_contractor,
        project.property_manager,
    ]
    filled = sum(1 for f in team_fields if f is not None and str(f).strip())
    raw = (filled / len(team_fields)) * 100.0

    # Bonus for data completeness
    if project.data_completeness is not None:
        # Blend in data quality: weight 70% team, 30% data completeness
        raw = raw * 0.7 + (project.data_completeness * 100.0) * 0.3

    detail = f"{filled}/{len(team_fields)} team roles filled."

    weight = HEALTH_WEIGHTS["team"]
    return DimensionScore(
        dimension="team",
        raw_score=round(raw, 1),
        weight=weight,
        weighted_score=round(raw * weight, 2),
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Health category mapping
# ---------------------------------------------------------------------------


def _score_to_health(score: float) -> OverallHealth:
    """Map a composite score to an OverallHealth enum."""
    thresholds = _load_national_benchmarks().get("health_thresholds", {})
    on_track = thresholds.get("on_track", 80)
    at_risk = thresholds.get("at_risk", 60)
    delayed = thresholds.get("delayed", 40)

    if score >= on_track:
        return OverallHealth.ON_TRACK
    elif score >= at_risk:
        return OverallHealth.AT_RISK
    elif score >= delayed:
        return OverallHealth.DELAYED
    else:
        return OverallHealth.STALLED


def _terminal_assessment(project: Project) -> HealthAssessmentResult:
    """Return a fixed assessment for terminal-stage projects."""
    stage = project.current_stage.value
    if project.current_stage == PipelineStage.OPERATIONS:
        score = 100.0
        health = OverallHealth.ON_TRACK
    else:
        score = 0.0
        health = OverallHealth.STALLED

    empty_dim = DimensionScore(
        dimension="n/a",
        raw_score=score,
        weight=0.0,
        weighted_score=0.0,
        detail=f"Project in terminal stage: {stage}.",
    )

    return HealthAssessmentResult(
        project_id=str(project.project_id),
        project_name=project.project_name,
        current_stage=stage,
        composite_score=score,
        overall_health=health.value,
        dimensions={
            "timeline": empty_dim,
            "budget": empty_dim,
            "funding": empty_dim,
            "risk": empty_dim,
            "team": empty_dim,
        },
        previous_score=float(project.health_score) if project.health_score else None,
        score_trend="stable",
        recommendations=[],
        assessed_at=datetime.utcnow().isoformat(),
    )


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------


def _generate_recommendations(
    project: Project,
    dimensions: dict[str, DimensionScore],
    overall: OverallHealth,
) -> list[str]:
    """Generate prioritized recommendations based on lowest-scoring dimensions."""
    recs: list[str] = []

    # Sort dimensions by raw_score ascending (worst first)
    sorted_dims = sorted(
        dimensions.values(),
        key=lambda d: d["raw_score"],
    )

    for dim in sorted_dims:
        if dim["raw_score"] >= 80:
            continue

        name = dim["dimension"]
        score = dim["raw_score"]

        if name == "timeline" and score < 60:
            recs.append(
                "Timeline is significantly behind peer benchmarks. "
                "Consider escalating pending approvals or re-sequencing "
                "activities to recover schedule."
            )
        elif name == "timeline" and score < 80:
            recs.append(
                "Timeline is slightly behind peers. Monitor closely and "
                "identify critical-path blockers."
            )

        if name == "budget" and score < 60:
            recs.append(
                "Budget variance exceeds acceptable thresholds. "
                "Conduct a cost reconciliation and identify value-engineering "
                "opportunities."
            )
        elif name == "budget" and score < 80:
            recs.append(
                "Budget is trending over original estimates. "
                "Review change orders and soft cost assumptions."
            )

        if name == "funding" and score < 50:
            recs.append(
                "Significant funding gap remains. Explore additional subsidy "
                "sources, request increased allocations, or adjust project "
                "scope to close the gap."
            )
        elif name == "funding" and score < 80:
            recs.append(
                "Not all funding sources are committed. Follow up on "
                "outstanding applications and closing timelines."
            )

        if name == "risk" and score < 50:
            recs.append(
                "High risk exposure detected. Address neighbor opposition, "
                "pending appeals, and jurisdiction friction points."
            )
        elif name == "risk" and score < 80:
            recs.append(
                "Moderate risk factors present. Proactive community "
                "engagement and political liaison recommended."
            )

        if name == "team" and score < 60:
            recs.append(
                "Key team roles are unfilled. Engage an architect, GC, "
                "or property manager to strengthen the development team."
            )

    # Cap recommendations
    return recs[:5]
