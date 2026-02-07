"""Timeline prediction endpoints.

Provides machine-learning-backed predictions for project milestones and
completion dates, along with confidence intervals and comparable project
benchmarks.
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

from src.api.dependencies import DbSession
from src.models.enums import BuildingType, PipelineStage
from src.models.project import Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/predictions", tags=["predictions"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class MilestonePrediction(BaseModel):
    """Predicted date range for a single pipeline milestone."""

    milestone: str = Field(..., description="Name of the milestone (e.g. 'entitlement_complete')")
    predicted_date: date | None = Field(None, description="Best-estimate date")
    optimistic_date: date | None = Field(None, description="P25 (optimistic) date")
    pessimistic_date: date | None = Field(None, description="P75 (pessimistic) date")
    confidence: float | None = Field(
        None, ge=0, le=1, description="Model confidence (0-1)"
    )
    days_from_now: int | None = Field(
        None, description="Predicted days from today to milestone"
    )

    model_config = {"from_attributes": True}


class PeerBenchmark(BaseModel):
    """Duration statistics from comparable completed projects."""

    stage: str
    peer_count: int = Field(..., description="Number of comparable projects")
    median_days: float | None = None
    p25_days: float | None = None
    p75_days: float | None = None

    model_config = {"from_attributes": True}


class TimelinePredictionResponse(BaseModel):
    """Full timeline prediction for a project."""

    project_id: uuid.UUID
    project_name: str
    current_stage: PipelineStage
    prediction_generated_at: str
    model_version: str | None = None

    milestones: list[MilestonePrediction]
    peer_benchmarks: list[PeerBenchmark]

    overall_confidence: float | None = Field(
        None, ge=0, le=1, description="Aggregate confidence across all milestones"
    )
    estimated_total_remaining_days: int | None = Field(
        None, description="Estimated days until the project reaches operations"
    )
    risk_factors_affecting_timeline: list[str] = Field(
        default_factory=list,
        description="Key risk factors that may shift the prediction",
    )

    model_config = {"from_attributes": True}


class BulkPredictionItem(BaseModel):
    """Lightweight prediction for a single project in a bulk response."""

    project_id: uuid.UUID
    project_name: str
    current_stage: PipelineStage
    predicted_groundbreaking: date | None = None
    predicted_co: date | None = None
    confidence: float | None = None

    model_config = {"from_attributes": True}


class BulkPredictionResponse(BaseModel):
    """Multiple project predictions."""

    generated_at: str
    predictions: list[BulkPredictionItem]
    total: int

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Peer benchmark helper
# ---------------------------------------------------------------------------

_STAGE_DURATION_FIELDS = {
    "concept": Project.concept_duration_days,
    "pre_development": Project.pre_development_duration_days,
    "entitlement": Project.entitlement_duration_days,
    "financing": Project.financing_duration_days,
    "construction": Project.construction_duration_days,
    "lease_up": Project.lease_up_duration_days,
}


def _compute_peer_benchmarks(
    db: Session,
    project: Project,
) -> list[PeerBenchmark]:
    """Compute peer duration benchmarks from completed comparable projects.

    Comparable projects share the same state, similar unit count (+/-30 %),
    and the same building type (when known).
    """
    benchmarks: list[PeerBenchmark] = []

    unit_low = int(project.total_units * 0.7) if project.total_units else 0
    unit_high = int(project.total_units * 1.3) if project.total_units else 10_000

    for stage_name, duration_col in _STAGE_DURATION_FIELDS.items():
        stmt = select(
            func.count(Project.project_id).label("cnt"),
            func.avg(duration_col).label("avg_d"),
            func.min(duration_col).label("min_d"),
            func.max(duration_col).label("max_d"),
        ).where(
            duration_col.isnot(None),
            Project.total_units >= unit_low,
            Project.total_units <= unit_high,
        )

        if project.state:
            stmt = stmt.where(Project.state == project.state)
        if project.building_type:
            stmt = stmt.where(Project.building_type == project.building_type)

        row = db.execute(stmt).first()
        if row and row.cnt and row.cnt > 0:
            benchmarks.append(
                PeerBenchmark(
                    stage=stage_name,
                    peer_count=row.cnt,
                    median_days=round(float(row.avg_d), 1) if row.avg_d else None,
                    p25_days=round(float(row.min_d), 1) if row.min_d else None,
                    p75_days=round(float(row.max_d), 1) if row.max_d else None,
                )
            )
        else:
            benchmarks.append(
                PeerBenchmark(stage=stage_name, peer_count=0)
            )

    return benchmarks


def _build_fallback_prediction(
    project: Project,
    benchmarks: list[PeerBenchmark],
) -> list[MilestonePrediction]:
    """Build milestone predictions from peer averages when no ML model is available."""
    milestones: list[MilestonePrediction] = []
    today = date.today()

    # Determine which stages remain.
    stage_order = [
        PipelineStage.CONCEPT,
        PipelineStage.PRE_DEVELOPMENT,
        PipelineStage.ENTITLEMENT,
        PipelineStage.FINANCING,
        PipelineStage.CONSTRUCTION,
        PipelineStage.LEASE_UP,
    ]

    try:
        current_idx = stage_order.index(project.current_stage)
    except ValueError:
        return milestones

    cursor = today
    for idx in range(current_idx, len(stage_order)):
        stage = stage_order[idx]
        stage_name = stage.value

        # Find the matching benchmark.
        bm = next((b for b in benchmarks if b.stage == stage_name), None)
        if bm and bm.median_days:
            days = int(bm.median_days)
        else:
            # Default estimates when no peers exist.
            defaults = {
                "concept": 120,
                "pre_development": 180,
                "entitlement": 270,
                "financing": 180,
                "construction": 540,
                "lease_up": 120,
            }
            days = defaults.get(stage_name, 180)

        predicted = cursor + timedelta(days=days)
        optimistic = cursor + timedelta(days=int(days * 0.7))
        pessimistic = cursor + timedelta(days=int(days * 1.4))

        milestones.append(
            MilestonePrediction(
                milestone=f"{stage_name}_complete",
                predicted_date=predicted,
                optimistic_date=optimistic,
                pessimistic_date=pessimistic,
                confidence=0.4 if not bm or bm.peer_count < 3 else 0.65,
                days_from_now=(predicted - today).days,
            )
        )
        cursor = predicted

    return milestones


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/{project_id}/timeline",
    response_model=TimelinePredictionResponse,
    summary="Predict project timeline",
)
def predict_project_timeline(
    project_id: uuid.UUID,
    db: DbSession,
) -> TimelinePredictionResponse:
    """Generate a timeline prediction for a single project.

    When the ``src.analytics.predict_project_timeline`` function (backed
    by a trained ML model) is available it is used.  Otherwise a
    peer-benchmark-based heuristic is applied.

    The response includes:

    * Per-milestone predicted, optimistic, and pessimistic dates.
    * Peer benchmarks from comparable completed projects.
    * Risk factors that could shift the predictions.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    # Peer benchmarks are always useful.
    benchmarks = _compute_peer_benchmarks(db, project)

    # Try the analytics ML predictor.
    try:
        from src.analytics import predict_project_timeline as _predict
        result = _predict(db, project_id=project_id)
        milestones = [MilestonePrediction(**m) for m in result.get("milestones", [])]
        overall_confidence = result.get("overall_confidence")
        remaining_days = result.get("estimated_total_remaining_days")
        risk_factors = result.get("risk_factors_affecting_timeline", [])
        model_version = result.get("model_version")
    except (ImportError, AttributeError):
        milestones = _build_fallback_prediction(project, benchmarks)
        overall_confidence = (
            sum(m.confidence for m in milestones if m.confidence) / len(milestones)
            if milestones
            else None
        )
        remaining_days = (
            max((m.days_from_now for m in milestones if m.days_from_now), default=None)
        )
        risk_factors = []
        model_version = "peer-benchmark-heuristic"

        # Derive risk factors from project attributes.
        if project.jurisdiction_friction_score and project.jurisdiction_friction_score > 60:
            risk_factors.append(
                f"High jurisdiction friction score ({project.jurisdiction_friction_score})"
            )
        if project.neighbor_opposition_level and project.neighbor_opposition_level.value in (
            "high", "severe"
        ):
            risk_factors.append(
                f"Neighbor opposition level: {project.neighbor_opposition_level.value}"
            )
        if project.funding_gap and float(project.funding_gap) > 0:
            risk_factors.append(
                f"Outstanding funding gap: ${float(project.funding_gap):,.0f}"
            )
        if project.appeals_filed and project.appeals_filed > 0:
            risk_factors.append(
                f"{project.appeals_filed} appeal(s) filed"
            )

    return TimelinePredictionResponse(
        project_id=project.project_id,
        project_name=project.project_name,
        current_stage=project.current_stage,
        prediction_generated_at=datetime.utcnow().isoformat(),
        model_version=model_version,
        milestones=milestones,
        peer_benchmarks=benchmarks,
        overall_confidence=overall_confidence,
        estimated_total_remaining_days=remaining_days,
        risk_factors_affecting_timeline=risk_factors,
    )


@router.get(
    "/bulk",
    response_model=BulkPredictionResponse,
    summary="Bulk timeline predictions",
)
def bulk_predict(
    db: DbSession,
    jurisdiction: str | None = Query(None, description="Filter by jurisdiction"),
    state: str | None = Query(None, max_length=2, description="Filter by state"),
    current_stage: PipelineStage | None = Query(None, description="Filter by stage"),
    limit: int = Query(50, ge=1, le=200, description="Max projects to predict"),
) -> BulkPredictionResponse:
    """Generate lightweight timeline predictions for multiple projects.

    Returns the predicted groundbreaking and certificate-of-occupancy dates
    along with a confidence score for each matching project.  Useful for
    portfolio-level forecasting dashboards.
    """
    stmt = select(Project).where(
        Project.current_stage.in_([
            PipelineStage.CONCEPT,
            PipelineStage.PRE_DEVELOPMENT,
            PipelineStage.ENTITLEMENT,
            PipelineStage.FINANCING,
            PipelineStage.CONSTRUCTION,
            PipelineStage.LEASE_UP,
        ])
    )
    if jurisdiction:
        stmt = stmt.where(Project.jurisdiction == jurisdiction)
    if state:
        stmt = stmt.where(Project.state == state.upper())
    if current_stage:
        stmt = stmt.where(Project.current_stage == current_stage)

    stmt = stmt.order_by(Project.updated_at.desc()).limit(limit)
    projects = list(db.scalars(stmt).all())

    items: list[BulkPredictionItem] = []
    for p in projects:
        # Use stored predictions when available.
        if p.predicted_groundbreaking or p.predicted_co:
            items.append(
                BulkPredictionItem(
                    project_id=p.project_id,
                    project_name=p.project_name,
                    current_stage=p.current_stage,
                    predicted_groundbreaking=p.predicted_groundbreaking,
                    predicted_co=p.predicted_co,
                    confidence=p.prediction_confidence,
                )
            )
        else:
            # Quick heuristic: estimate from peer averages.
            benchmarks = _compute_peer_benchmarks(db, p)
            milestones = _build_fallback_prediction(p, benchmarks)
            groundbreaking = next(
                (m.predicted_date for m in milestones if m.milestone == "construction_complete"),
                None,
            )
            co = next(
                (m.predicted_date for m in milestones if m.milestone == "lease_up_complete"),
                None,
            )
            avg_conf = (
                sum(m.confidence for m in milestones if m.confidence) / len(milestones)
                if milestones
                else None
            )
            items.append(
                BulkPredictionItem(
                    project_id=p.project_id,
                    project_name=p.project_name,
                    current_stage=p.current_stage,
                    predicted_groundbreaking=groundbreaking,
                    predicted_co=co,
                    confidence=round(avg_conf, 2) if avg_conf else None,
                )
            )

    return BulkPredictionResponse(
        generated_at=datetime.utcnow().isoformat(),
        predictions=items,
        total=len(items),
    )
