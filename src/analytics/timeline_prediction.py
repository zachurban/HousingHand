"""Predictive timeline model using peer data and friction scores.

Estimates remaining duration and projected milestone dates for
in-progress projects by combining peer benchmarks, jurisdiction-specific
friction adjustments, and project-level risk factors. Predictions are
expressed as point estimates with confidence intervals.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import TypedDict
from uuid import UUID

import numpy as np
from sqlalchemy.orm import Session

from src.analytics.peer_benchmarking import (
    PeerBenchmarkResult,
    _ACTIVE_STAGES,
    _extract_stage_durations,
    _load_national_benchmarks,
    compute_peer_benchmarks,
)
from src.database.queries import get_project, query_similar_projects
from src.models.enums import OverallHealth, PipelineStage
from src.models.project import Project

logger = logging.getLogger(__name__)


# Stages in sequential order for remaining-stage calculations
_STAGE_ORDER: list[str] = [
    "concept",
    "pre_development",
    "entitlement",
    "financing",
    "construction",
    "lease_up",
]

_TERMINAL_STAGES = {"operations", "abandoned", "stalled"}


# ---------------------------------------------------------------------------
# Typed results
# ---------------------------------------------------------------------------


class StagePrediction(TypedDict):
    """Predicted duration for one remaining pipeline stage."""

    stage: str
    predicted_days: float
    peer_median_days: float
    friction_adjustment_days: float
    risk_adjustment_days: float
    confidence_low_days: float
    confidence_high_days: float


class TimelinePredictionResult(TypedDict):
    """Full timeline prediction for a project."""

    project_id: str
    project_name: str
    current_stage: str
    days_in_current_stage: int | None
    predicted_remaining_days: float
    predicted_total_days: float
    predicted_groundbreaking: str | None  # ISO date
    predicted_co: str | None  # ISO date (certificate of occupancy)
    confidence: float  # 0.0 - 1.0
    confidence_interval_days: tuple[float, float]
    stage_predictions: list[StagePrediction]
    friction_score_used: int | None
    peer_group_name: str
    method: str  # "peer_adjusted", "national_adjusted", "extrapolation"
    predicted_at: str


class BatchTimelinePredictionResult(TypedDict):
    """Batch prediction summary."""

    total_predicted: int
    average_remaining_days: float
    median_remaining_days: float
    average_confidence: float
    predictions: list[TimelinePredictionResult]
    predicted_at: str


# ---------------------------------------------------------------------------
# Single project prediction
# ---------------------------------------------------------------------------


def predict_project_timeline(
    db: Session,
    project_id: UUID,
    peer_benchmark: PeerBenchmarkResult | None = None,
) -> TimelinePredictionResult:
    """Predict remaining timeline for a single project.

    The prediction combines three inputs:
    1. Peer benchmark median durations for each remaining stage.
    2. Jurisdiction friction score adjustment (higher friction -> longer).
    3. Project-level risk factors (opposition, appeals, etc.).

    Confidence is reduced when fewer peer data points are available or
    when friction/risk adjustments are large.

    Args:
        db: SQLAlchemy session.
        project_id: UUID of the project to predict.
        peer_benchmark: Optional pre-computed peer benchmarks.

    Returns:
        TimelinePredictionResult with stage-by-stage predictions and
        projected milestone dates.

    Raises:
        ValueError: If project is not found.
    """
    project = get_project(db, project_id)
    if project is None:
        raise ValueError(f"Project {project_id} not found.")

    current_stage_val = project.current_stage.value

    if current_stage_val in _TERMINAL_STAGES:
        return _terminal_prediction(project)

    # Compute peer benchmarks if not provided
    if peer_benchmark is None:
        peer_benchmark = compute_peer_benchmarks(
            db,
            jurisdiction=project.jurisdiction,
            state=project.state,
            building_type=(
                project.building_type.value if project.building_type else None
            ),
        )

    method = (
        "peer_adjusted"
        if peer_benchmark["project_count"] > 0
        else "national_adjusted"
    )

    # Compute friction and risk adjustments
    friction_score = project.jurisdiction_friction_score
    friction_multiplier = _friction_to_multiplier(friction_score)
    risk_multiplier = _risk_to_multiplier(project)

    # Determine remaining stages
    remaining_stages = _get_remaining_stages(current_stage_val)

    # Build per-stage predictions
    stage_predictions: list[StagePrediction] = []
    total_remaining = 0.0
    total_low = 0.0
    total_high = 0.0
    confidence_factors: list[float] = []

    for stage in remaining_stages:
        bench = peer_benchmark["stage_benchmarks"].get(stage)

        if bench and bench["median_days"] > 0:
            base_days = bench["median_days"]
            sample_size = bench["sample_size"]
        else:
            # Fall back to national
            national = _load_national_benchmarks()
            nat_stage = national.get("stage_durations", {}).get(stage, {})
            base_days = float(nat_stage.get("median", 180))
            sample_size = 0

        # Apply friction adjustment (primarily affects entitlement/pre-dev)
        if stage in ("entitlement", "pre_development"):
            friction_adj = base_days * (friction_multiplier - 1.0)
        else:
            friction_adj = base_days * (friction_multiplier - 1.0) * 0.3

        # Apply risk adjustment
        risk_adj = base_days * (risk_multiplier - 1.0)

        predicted = base_days + friction_adj + risk_adj

        # For the current stage, subtract days already spent
        if stage == current_stage_val and project.days_in_current_stage:
            predicted = max(0.0, predicted - project.days_in_current_stage)
            friction_adj = max(0.0, friction_adj)
            risk_adj = max(0.0, risk_adj)

        # Confidence interval: use p25/p75 if available, else +/- 30%
        if bench and bench["p25_days"] > 0:
            ci_low = bench["p25_days"]
            ci_high = bench["p75_days"]
            # Adjust CI for friction/risk
            ci_low = ci_low * friction_multiplier * risk_multiplier
            ci_high = ci_high * friction_multiplier * risk_multiplier
            if stage == current_stage_val and project.days_in_current_stage:
                ci_low = max(0.0, ci_low - project.days_in_current_stage)
                ci_high = max(0.0, ci_high - project.days_in_current_stage)
        else:
            ci_low = predicted * 0.7
            ci_high = predicted * 1.5

        # Per-stage confidence based on sample size
        if sample_size >= 20:
            stage_conf = 0.85
        elif sample_size >= 10:
            stage_conf = 0.70
        elif sample_size >= 5:
            stage_conf = 0.55
        else:
            stage_conf = 0.35
        confidence_factors.append(stage_conf)

        stage_predictions.append(
            StagePrediction(
                stage=stage,
                predicted_days=round(predicted, 1),
                peer_median_days=base_days,
                friction_adjustment_days=round(friction_adj, 1),
                risk_adjustment_days=round(risk_adj, 1),
                confidence_low_days=round(ci_low, 1),
                confidence_high_days=round(ci_high, 1),
            )
        )

        total_remaining += predicted
        total_low += ci_low
        total_high += ci_high

    # Overall confidence
    if confidence_factors:
        base_confidence = float(np.mean(confidence_factors))
    else:
        base_confidence = 0.3

    # Penalize confidence for high friction / risk
    adj_penalty = (friction_multiplier - 1.0) * 0.1 + (risk_multiplier - 1.0) * 0.1
    confidence = max(0.1, min(0.95, base_confidence - adj_penalty))

    # Predicted total from concept
    elapsed = project.total_elapsed_days or 0
    predicted_total = elapsed + total_remaining

    # Projected dates
    today = date.today()
    predicted_groundbreaking = _project_milestone_date(
        project, stage_predictions, "construction", today
    )
    predicted_co = _project_milestone_date(
        project, stage_predictions, "lease_up", today
    )

    return TimelinePredictionResult(
        project_id=str(project.project_id),
        project_name=project.project_name,
        current_stage=current_stage_val,
        days_in_current_stage=project.days_in_current_stage,
        predicted_remaining_days=round(total_remaining, 1),
        predicted_total_days=round(predicted_total, 1),
        predicted_groundbreaking=(
            predicted_groundbreaking.isoformat()
            if predicted_groundbreaking
            else None
        ),
        predicted_co=(
            predicted_co.isoformat() if predicted_co else None
        ),
        confidence=round(confidence, 3),
        confidence_interval_days=(round(total_low, 1), round(total_high, 1)),
        stage_predictions=stage_predictions,
        friction_score_used=friction_score,
        peer_group_name=peer_benchmark["peer_group_name"],
        method=method,
        predicted_at=datetime.utcnow().isoformat(),
    )


# ---------------------------------------------------------------------------
# Batch prediction
# ---------------------------------------------------------------------------


def predict_batch_timelines(
    db: Session,
    *,
    jurisdiction: str | None = None,
    state: str | None = None,
    stages: list[PipelineStage] | None = None,
    limit: int = 500,
) -> BatchTimelinePredictionResult:
    """Predict timelines for multiple projects.

    Args:
        db: SQLAlchemy session.
        jurisdiction: Optional jurisdiction filter.
        state: Optional state filter.
        stages: Optional pipeline stage filter.
        limit: Maximum projects to predict.

    Returns:
        BatchTimelinePredictionResult with summary statistics and
        individual predictions.
    """
    from src.database.queries import query_projects

    active_stages = stages or [
        s for s in PipelineStage if s.value not in _TERMINAL_STAGES
    ]

    projects = query_projects(
        db,
        jurisdiction=jurisdiction,
        state=state,
        stages=active_stages,
        limit=limit,
    )

    # Pre-compute peer benchmark once
    peer_benchmark = compute_peer_benchmarks(
        db,
        jurisdiction=jurisdiction,
        state=state,
    )

    predictions: list[TimelinePredictionResult] = []

    for project in projects:
        try:
            pred = predict_project_timeline(
                db, project.project_id, peer_benchmark
            )
            predictions.append(pred)
        except Exception:
            logger.exception(
                "Failed timeline prediction for project %s.",
                project.project_id,
            )

    remaining_days = [p["predicted_remaining_days"] for p in predictions]
    confidences = [p["confidence"] for p in predictions]

    arr = np.array(remaining_days) if remaining_days else np.array([0.0])
    conf_arr = np.array(confidences) if confidences else np.array([0.0])

    return BatchTimelinePredictionResult(
        total_predicted=len(predictions),
        average_remaining_days=float(np.mean(arr)),
        median_remaining_days=float(np.median(arr)),
        average_confidence=float(np.mean(conf_arr)),
        predictions=predictions,
        predicted_at=datetime.utcnow().isoformat(),
    )


# ---------------------------------------------------------------------------
# Friction-based prediction for new projects
# ---------------------------------------------------------------------------


def predict_from_friction_score(
    db: Session,
    *,
    jurisdiction: str,
    friction_score: int,
    total_units: int = 50,
    building_type: str | None = None,
    state: str | None = None,
) -> TimelinePredictionResult:
    """Predict timeline for a hypothetical project using friction score.

    Useful for "what-if" analysis: given a jurisdiction's friction score,
    how long should a typical project expect to take?

    Args:
        db: SQLAlchemy session.
        jurisdiction: Target jurisdiction.
        friction_score: Jurisdiction friction score (1-100).
        total_units: Assumed project size.
        building_type: Optional building type.
        state: State code for peer matching.

    Returns:
        TimelinePredictionResult for the hypothetical project.
    """
    peer_benchmark = compute_peer_benchmarks(
        db,
        jurisdiction=jurisdiction,
        state=state,
        building_type=building_type,
    )

    friction_multiplier = _friction_to_multiplier(friction_score)
    stage_predictions: list[StagePrediction] = []
    total_days = 0.0
    total_low = 0.0
    total_high = 0.0

    for stage in _STAGE_ORDER:
        bench = peer_benchmark["stage_benchmarks"].get(stage)
        if bench and bench["median_days"] > 0:
            base = bench["median_days"]
        else:
            national = _load_national_benchmarks()
            base = float(
                national.get("stage_durations", {})
                .get(stage, {})
                .get("median", 180)
            )

        if stage in ("entitlement", "pre_development"):
            friction_adj = base * (friction_multiplier - 1.0)
        else:
            friction_adj = base * (friction_multiplier - 1.0) * 0.3

        predicted = base + friction_adj
        ci_low = predicted * 0.7
        ci_high = predicted * 1.5

        stage_predictions.append(
            StagePrediction(
                stage=stage,
                predicted_days=round(predicted, 1),
                peer_median_days=base,
                friction_adjustment_days=round(friction_adj, 1),
                risk_adjustment_days=0.0,
                confidence_low_days=round(ci_low, 1),
                confidence_high_days=round(ci_high, 1),
            )
        )

        total_days += predicted
        total_low += ci_low
        total_high += ci_high

    today = date.today()
    groundbreaking_offset = sum(
        sp["predicted_days"]
        for sp in stage_predictions
        if sp["stage"] in ("concept", "pre_development", "entitlement", "financing")
    )
    co_offset = total_days

    return TimelinePredictionResult(
        project_id="hypothetical",
        project_name=f"Hypothetical ({jurisdiction}, friction={friction_score})",
        current_stage="concept",
        days_in_current_stage=0,
        predicted_remaining_days=round(total_days, 1),
        predicted_total_days=round(total_days, 1),
        predicted_groundbreaking=(
            (today + timedelta(days=int(groundbreaking_offset))).isoformat()
        ),
        predicted_co=(
            (today + timedelta(days=int(co_offset))).isoformat()
        ),
        confidence=0.45,  # Lower confidence for hypothetical
        confidence_interval_days=(round(total_low, 1), round(total_high, 1)),
        stage_predictions=stage_predictions,
        friction_score_used=friction_score,
        peer_group_name=peer_benchmark["peer_group_name"],
        method="friction_projection",
        predicted_at=datetime.utcnow().isoformat(),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_remaining_stages(current_stage: str) -> list[str]:
    """Return stages remaining including the current stage."""
    if current_stage not in _STAGE_ORDER:
        return _STAGE_ORDER  # Full pipeline

    idx = _STAGE_ORDER.index(current_stage)
    return _STAGE_ORDER[idx:]


def _friction_to_multiplier(friction_score: int | None) -> float:
    """Convert a friction score (1-100) to a duration multiplier.

    A friction score of 50 (median) maps to 1.0x (no adjustment).
    A friction score of 100 maps to ~1.8x.
    A friction score of 1 maps to ~0.7x.

    The mapping uses a logistic-style curve centered at 50.
    """
    if friction_score is None:
        return 1.0

    score = max(1, min(100, friction_score))
    # Normalized to -1 .. +1 around the center of 50
    normalized = (score - 50) / 50.0

    # Asymmetric scaling: high friction has more impact than low
    if normalized >= 0:
        multiplier = 1.0 + normalized * 0.8  # Up to 1.8x
    else:
        multiplier = 1.0 + normalized * 0.3  # Down to 0.7x

    return round(multiplier, 3)


def _risk_to_multiplier(project: Project) -> float:
    """Convert project risk factors to a duration multiplier.

    Considers risk_score, appeals, opposition level, and design review
    iterations. Center is 1.0x; max is ~1.5x.
    """
    adjustments: list[float] = []

    # Risk score (0-100)
    if project.risk_score is not None:
        adjustments.append((project.risk_score - 50.0) / 100.0)

    # Appeals
    if project.appeals_filed and project.appeals_filed > 0:
        adjustments.append(min(0.3, project.appeals_filed * 0.1))

    # Neighbor opposition
    opp_map = {
        "none": -0.05,
        "low": 0.0,
        "moderate": 0.1,
        "high": 0.2,
        "severe": 0.35,
    }
    if project.neighbor_opposition_level is not None:
        adjustments.append(opp_map.get(project.neighbor_opposition_level.value, 0.0))

    # Design review iterations
    if project.design_review_iterations and project.design_review_iterations > 2:
        adjustments.append(min(0.2, (project.design_review_iterations - 2) * 0.05))

    if not adjustments:
        return 1.0

    total_adj = sum(adjustments)
    multiplier = 1.0 + total_adj
    return round(max(0.8, min(1.5, multiplier)), 3)


def _project_milestone_date(
    project: Project,
    stage_predictions: list[StagePrediction],
    target_stage: str,
    reference_date: date,
) -> date | None:
    """Calculate a projected date for reaching a target stage.

    Sums predicted days for stages between now and the target stage.
    """
    current_stage = project.current_stage.value
    if current_stage in _TERMINAL_STAGES:
        return None

    try:
        current_idx = _STAGE_ORDER.index(current_stage)
        target_idx = _STAGE_ORDER.index(target_stage)
    except ValueError:
        return None

    if current_idx >= target_idx:
        return None  # Already past this stage

    days_to_target = sum(
        sp["predicted_days"]
        for sp in stage_predictions
        if sp["stage"] in _STAGE_ORDER[current_idx:target_idx]
    )

    return reference_date + timedelta(days=int(days_to_target))


def _terminal_prediction(project: Project) -> TimelinePredictionResult:
    """Return a no-op prediction for terminal-stage projects."""
    return TimelinePredictionResult(
        project_id=str(project.project_id),
        project_name=project.project_name,
        current_stage=project.current_stage.value,
        days_in_current_stage=project.days_in_current_stage,
        predicted_remaining_days=0.0,
        predicted_total_days=float(project.total_elapsed_days or 0),
        predicted_groundbreaking=None,
        predicted_co=None,
        confidence=1.0,
        confidence_interval_days=(0.0, 0.0),
        stage_predictions=[],
        friction_score_used=project.jurisdiction_friction_score,
        peer_group_name="n/a",
        method="terminal",
        predicted_at=datetime.utcnow().isoformat(),
    )
