"""Policy reform impact measurement endpoints.

Allows stakeholders to track zoning changes, parking reforms, density
bonuses, and other regulatory reforms, and to measure their quantitative
impact on the affordable housing pipeline.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.dependencies import DbSession, PaginationDep
from src.models.enums import ConfidenceLevel, PipelineStage, ReformType
from src.models.project import Project
from src.models.reform import PolicyReform

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reforms", tags=["reforms"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ReformCreate(BaseModel):
    """Schema for registering a new policy reform."""

    jurisdiction: str = Field(..., min_length=1, max_length=300)
    reform_name: str = Field(..., min_length=1, max_length=500)
    reform_description: str | None = None
    reform_type: ReformType
    related_friction_topic: str | None = None

    announcement_date: date | None = None
    effective_date: date | None = None
    implementation_buffer_days: int = Field(30, ge=0)

    source: str | None = None
    source_url: str | None = None
    ordinance_number: str | None = None
    notes: str | None = None

    model_config = {"json_schema_extra": {
        "examples": [
            {
                "jurisdiction": "Minneapolis, MN",
                "reform_name": "2040 Comprehensive Plan - Parking Reform",
                "reform_type": "parking_reform",
                "effective_date": "2020-01-01",
                "related_friction_topic": "parking_minimum",
                "source": "City of Minneapolis",
            }
        ]
    }}


class ReformUpdate(BaseModel):
    """Partial update schema for a policy reform."""

    reform_name: str | None = Field(None, min_length=1, max_length=500)
    reform_description: str | None = None
    reform_type: ReformType | None = None
    related_friction_topic: str | None = None
    announcement_date: date | None = None
    effective_date: date | None = None
    implementation_buffer_days: int | None = Field(None, ge=0)
    source: str | None = None
    source_url: str | None = None
    ordinance_number: str | None = None
    notes: str | None = None

    model_config = {"from_attributes": True}


class ReformResponse(BaseModel):
    """Full policy reform detail."""

    reform_id: uuid.UUID
    jurisdiction: str
    reform_name: str
    reform_description: str | None = None
    reform_type: ReformType
    related_friction_topic: str | None = None

    announcement_date: date | None = None
    effective_date: date | None = None
    implementation_buffer_days: int

    # Impact metrics
    projects_pre_reform: int
    projects_post_reform: int
    pre_reform_median_days: int | None = None
    post_reform_median_days: int | None = None
    days_saved_per_project: int | None = None
    percent_improvement: float | None = None

    total_cost_savings: float | None = None
    units_enabled: int
    projects_no_longer_delayed: int

    statistical_significance_p_value: float | None = None
    confidence_level: ConfidenceLevel | None = None

    source: str | None = None
    source_url: str | None = None
    ordinance_number: str | None = None

    impact_last_measured: date | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReformListResponse(BaseModel):
    """Paginated list of policy reforms."""

    items: list[ReformResponse]
    total: int
    limit: int
    offset: int

    model_config = {"from_attributes": True}


class ReformImpactResult(BaseModel):
    """Quantified impact analysis for a single reform."""

    reform_id: uuid.UUID
    reform_name: str
    jurisdiction: str
    reform_type: ReformType
    effective_date: date | None = None

    # Before / after comparison
    projects_pre_reform: int
    projects_post_reform: int
    pre_reform_median_days: int | None = None
    post_reform_median_days: int | None = None
    days_saved_per_project: int | None = None
    percent_improvement: float | None = None

    # Cost impact
    avg_cost_per_delay_day: float | None = Field(
        None, description="Estimated carrying cost per day of delay"
    )
    total_cost_savings: float | None = None
    units_enabled: int = 0

    # Statistical quality
    statistical_significance_p_value: float | None = None
    confidence_level: ConfidenceLevel | None = None

    analysis_generated_at: str

    model_config = {"from_attributes": True}


class JurisdictionReformSummary(BaseModel):
    """Aggregate reform impact for a jurisdiction."""

    jurisdiction: str
    total_reforms: int
    reforms_with_measurable_impact: int
    total_days_saved: int
    total_cost_savings: float
    total_units_enabled: int
    most_impactful_reform: str | None = None
    avg_percent_improvement: float | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=ReformListResponse,
    summary="List policy reforms",
)
def list_reforms(
    db: DbSession,
    pagination: PaginationDep,
    jurisdiction: str | None = Query(None, description="Filter by jurisdiction"),
    reform_type: ReformType | None = Query(None, description="Filter by reform type"),
    state: str | None = Query(
        None, max_length=2, description="Filter by state (matches jurisdiction's state)"
    ),
    has_impact: bool | None = Query(
        None, description="Only reforms with measured impact (days_saved > 0)"
    ),
) -> ReformListResponse:
    """Return a paginated list of tracked policy reforms.

    Can be filtered by jurisdiction, reform type, and whether measured
    impact data exists.
    """
    stmt = select(PolicyReform)

    if jurisdiction:
        stmt = stmt.where(PolicyReform.jurisdiction == jurisdiction)
    if reform_type:
        stmt = stmt.where(PolicyReform.reform_type == reform_type)
    if state:
        stmt = stmt.where(PolicyReform.jurisdiction.ilike(f"%{state.upper()}%"))
    if has_impact is True:
        stmt = stmt.where(PolicyReform.days_saved_per_project > 0)
    elif has_impact is False:
        stmt = stmt.where(
            (PolicyReform.days_saved_per_project == None)  # noqa: E711
            | (PolicyReform.days_saved_per_project == 0)
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0

    stmt = stmt.order_by(PolicyReform.effective_date.desc().nullslast())
    stmt = stmt.limit(pagination.limit).offset(pagination.offset)
    reforms = list(db.scalars(stmt).all())

    return ReformListResponse(
        items=[ReformResponse.model_validate(r) for r in reforms],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get(
    "/{reform_id}",
    response_model=ReformResponse,
    summary="Get reform details",
)
def get_reform(
    reform_id: uuid.UUID,
    db: DbSession,
) -> ReformResponse:
    """Retrieve full details for a single policy reform."""
    reform = db.get(PolicyReform, reform_id)
    if reform is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy reform {reform_id} not found",
        )
    return ReformResponse.model_validate(reform)


@router.post(
    "",
    response_model=ReformResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new policy reform",
)
def create_reform(
    payload: ReformCreate,
    db: DbSession,
) -> ReformResponse:
    """Register a new regulatory reform for future impact measurement.

    Once registered, use ``POST /api/v1/reforms/{reform_id}/measure`` to
    compute the before/after impact analysis.
    """
    reform = PolicyReform(**payload.model_dump(exclude_unset=True))
    db.add(reform)

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to create policy reform")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create policy reform",
        )

    db.refresh(reform)
    return ReformResponse.model_validate(reform)


@router.patch(
    "/{reform_id}",
    response_model=ReformResponse,
    summary="Update a policy reform",
)
def update_reform(
    reform_id: uuid.UUID,
    payload: ReformUpdate,
    db: DbSession,
) -> ReformResponse:
    """Partially update a policy reform's metadata."""
    reform = db.get(PolicyReform, reform_id)
    if reform is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy reform {reform_id} not found",
        )

    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields provided for update",
        )

    for field, value in update_data.items():
        setattr(reform, field, value)
    reform.updated_at = datetime.utcnow()

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to update reform %s", reform_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update policy reform",
        )

    db.refresh(reform)
    return ReformResponse.model_validate(reform)


@router.post(
    "/{reform_id}/measure",
    response_model=ReformImpactResult,
    summary="Measure reform impact",
)
def measure_reform_impact(
    reform_id: uuid.UUID,
    db: DbSession,
    avg_cost_per_delay_day: float = Query(
        3500.0,
        ge=0,
        description="Estimated carrying/delay cost per day (used for cost-savings calculation)",
    ),
) -> ReformImpactResult:
    """Compute a before/after impact analysis for a registered reform.

    The analysis compares entitlement durations (or durations for the
    relevant stage) of projects that went through the pipeline before the
    reform's effective date to those that started after.  When the
    ``src.analytics.measure_policy_reform_impact`` function is available
    it is used for a statistically rigorous comparison; otherwise a
    simplified DB-driven approach is used.

    The ``avg_cost_per_delay_day`` parameter lets callers customize the
    carrying cost assumption used for total savings calculation.
    """
    reform = db.get(PolicyReform, reform_id)
    if reform is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy reform {reform_id} not found",
        )

    if not reform.effective_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot measure impact without an effective_date on the reform",
        )

    # Try the analytics module.
    try:
        from src.analytics import measure_policy_reform_impact as _measure
        result = _measure(
            db,
            reform_id=reform_id,
            avg_cost_per_delay_day=avg_cost_per_delay_day,
        )
        return ReformImpactResult(
            reform_id=reform.reform_id,
            reform_name=reform.reform_name,
            jurisdiction=reform.jurisdiction,
            reform_type=reform.reform_type,
            effective_date=reform.effective_date,
            avg_cost_per_delay_day=avg_cost_per_delay_day,
            analysis_generated_at=datetime.utcnow().isoformat(),
            **{k: v for k, v in result.items() if k not in (
                "reform_id", "reform_name", "jurisdiction", "reform_type",
                "effective_date", "avg_cost_per_delay_day", "analysis_generated_at",
            )},
        )
    except (ImportError, AttributeError):
        pass

    # Fallback: direct DB comparison.
    buffer = timedelta(days=reform.implementation_buffer_days)
    cutoff = reform.effective_date + buffer

    # Pre-reform: projects whose entitlement started before the effective date.
    pre_stmt = select(
        func.count(Project.project_id).label("cnt"),
        func.avg(Project.entitlement_duration_days).label("avg_days"),
    ).where(
        Project.jurisdiction == reform.jurisdiction,
        Project.entitlement_start < reform.effective_date,
        Project.entitlement_duration_days.isnot(None),
    )
    pre = db.execute(pre_stmt).first()
    pre_count = pre.cnt if pre else 0
    pre_avg = float(pre.avg_days) if pre and pre.avg_days else None

    # Post-reform: projects whose entitlement started after the cutoff.
    post_stmt = select(
        func.count(Project.project_id).label("cnt"),
        func.avg(Project.entitlement_duration_days).label("avg_days"),
    ).where(
        Project.jurisdiction == reform.jurisdiction,
        Project.entitlement_start >= cutoff,
        Project.entitlement_duration_days.isnot(None),
    )
    post = db.execute(post_stmt).first()
    post_count = post.cnt if post else 0
    post_avg = float(post.avg_days) if post and post.avg_days else None

    days_saved: int | None = None
    pct_improvement: float | None = None
    total_savings: float | None = None
    units_enabled = 0
    confidence = None

    if pre_avg is not None and post_avg is not None and pre_avg > 0:
        days_saved = int(pre_avg - post_avg)
        pct_improvement = round((pre_avg - post_avg) / pre_avg * 100, 1) if days_saved > 0 else 0.0
        total_savings = round(max(days_saved, 0) * avg_cost_per_delay_day * post_count, 2)

        # Rough confidence heuristic.
        if pre_count >= 10 and post_count >= 10:
            confidence = ConfidenceLevel.HIGH
        elif pre_count >= 5 and post_count >= 5:
            confidence = ConfidenceLevel.MODERATE
        else:
            confidence = ConfidenceLevel.LOW

    # Persist the results back to the reform record.
    reform.projects_pre_reform = pre_count
    reform.projects_post_reform = post_count
    reform.pre_reform_median_days = int(pre_avg) if pre_avg else None
    reform.post_reform_median_days = int(post_avg) if post_avg else None
    reform.days_saved_per_project = days_saved
    reform.percent_improvement = pct_improvement
    reform.total_cost_savings = total_savings
    reform.units_enabled = units_enabled
    reform.confidence_level = confidence
    reform.impact_last_measured = date.today()
    reform.updated_at = datetime.utcnow()

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to persist impact results for reform %s", reform_id)

    return ReformImpactResult(
        reform_id=reform.reform_id,
        reform_name=reform.reform_name,
        jurisdiction=reform.jurisdiction,
        reform_type=reform.reform_type,
        effective_date=reform.effective_date,
        projects_pre_reform=pre_count,
        projects_post_reform=post_count,
        pre_reform_median_days=int(pre_avg) if pre_avg else None,
        post_reform_median_days=int(post_avg) if post_avg else None,
        days_saved_per_project=days_saved,
        percent_improvement=pct_improvement,
        avg_cost_per_delay_day=avg_cost_per_delay_day,
        total_cost_savings=total_savings,
        units_enabled=units_enabled,
        confidence_level=confidence,
        analysis_generated_at=datetime.utcnow().isoformat(),
    )


@router.get(
    "/jurisdictions/summary",
    response_model=list[JurisdictionReformSummary],
    summary="Reform impact summary by jurisdiction",
)
def jurisdiction_reform_summary(
    db: DbSession,
    state: str | None = Query(None, max_length=2, description="Filter by state"),
    reform_type: ReformType | None = Query(None, description="Filter by reform type"),
    limit: int = Query(20, ge=1, le=100, description="Max jurisdictions to return"),
) -> list[JurisdictionReformSummary]:
    """Aggregate reform impact grouped by jurisdiction.

    Shows which jurisdictions have been most active in passing reforms
    and which reforms have had the largest measurable impact.
    """
    stmt = (
        select(
            PolicyReform.jurisdiction,
            func.count(PolicyReform.reform_id).label("total_reforms"),
            func.sum(
                func.coalesce(PolicyReform.days_saved_per_project, 0)
                * func.coalesce(PolicyReform.projects_post_reform, 0)
            ).label("total_days_saved"),
            func.coalesce(func.sum(PolicyReform.total_cost_savings), 0).label(
                "total_cost_savings"
            ),
            func.coalesce(func.sum(PolicyReform.units_enabled), 0).label(
                "total_units_enabled"
            ),
            func.avg(PolicyReform.percent_improvement).label("avg_pct"),
        )
        .group_by(PolicyReform.jurisdiction)
        .order_by(func.count(PolicyReform.reform_id).desc())
    )

    if state:
        stmt = stmt.where(PolicyReform.jurisdiction.ilike(f"%{state.upper()}%"))
    if reform_type:
        stmt = stmt.where(PolicyReform.reform_type == reform_type)

    stmt = stmt.limit(limit)
    rows = db.execute(stmt).all()

    results: list[JurisdictionReformSummary] = []
    for r in rows:
        # Find most impactful reform for this jurisdiction.
        best_stmt = (
            select(PolicyReform.reform_name)
            .where(
                PolicyReform.jurisdiction == r.jurisdiction,
                PolicyReform.days_saved_per_project.isnot(None),
            )
            .order_by(PolicyReform.days_saved_per_project.desc())
            .limit(1)
        )
        best_name = db.scalar(best_stmt)

        # Count reforms with measurable positive impact.
        measurable_stmt = select(func.count()).where(
            PolicyReform.jurisdiction == r.jurisdiction,
            PolicyReform.days_saved_per_project > 0,
        )
        measurable_count = db.scalar(measurable_stmt) or 0

        results.append(
            JurisdictionReformSummary(
                jurisdiction=r.jurisdiction,
                total_reforms=r.total_reforms,
                reforms_with_measurable_impact=measurable_count,
                total_days_saved=int(r.total_days_saved or 0),
                total_cost_savings=float(r.total_cost_savings or 0),
                total_units_enabled=int(r.total_units_enabled or 0),
                most_impactful_reform=best_name,
                avg_percent_improvement=(
                    round(float(r.avg_pct), 1) if r.avg_pct else None
                ),
            )
        )

    return results
