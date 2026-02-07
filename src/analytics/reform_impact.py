"""Policy reform impact measurement with statistical testing.

Measures the effect of zoning changes, parking reforms, density bonuses,
streamlining, and fee reductions on housing development timelines and
costs. Uses pre/post comparison with t-tests (or Mann-Whitney when
normality is violated) to determine statistical significance.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import TypedDict
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.analytics.peer_benchmarking import _load_national_benchmarks
from src.analytics.statistical_tests import (
    ConfidenceIntervalResult,
    TTestResult,
    confidence_interval,
    independent_ttest,
    mann_whitney_test,
    select_and_run_test,
)
from src.database.queries import (
    get_abandoned_projects,
    get_projects_by_entitlement_window,
    query_projects,
)
from src.models.enums import ConfidenceLevel, PipelineStage, ReformType
from src.models.project import Project
from src.models.reform import PolicyReform

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed results
# ---------------------------------------------------------------------------


class ReformImpactResult(TypedDict):
    """Complete impact assessment for a single policy reform."""

    reform_id: str
    reform_name: str
    jurisdiction: str
    reform_type: str
    effective_date: str | None

    # Sample sizes
    pre_reform_n: int
    post_reform_n: int

    # Duration metrics
    pre_reform_median_days: float
    post_reform_median_days: float
    days_saved_per_project: float
    percent_improvement: float

    # Statistical test
    test_used: str  # "ttest" or "mann_whitney"
    p_value: float
    is_significant: bool
    effect_size: float
    effect_interpretation: str
    confidence_interval_days_saved: tuple[float, float]

    # Broader impact
    total_cost_savings: float
    units_enabled: int
    projects_unblocked: int
    stall_rate_change: float  # negative = improvement

    # Confidence
    confidence_level: str  # ConfidenceLevel value
    caveats: list[str]

    measured_at: str


class MultiReformComparisonResult(TypedDict):
    """Comparison of multiple reforms in a jurisdiction."""

    jurisdiction: str
    reforms_analyzed: int
    reform_results: list[ReformImpactResult]
    most_impactful_reform: str | None
    total_days_saved_all_reforms: float
    total_cost_savings_all_reforms: float
    total_units_enabled: int
    measured_at: str


class ReformTimeSeriesPoint(TypedDict):
    """Single data point in a reform time series."""

    period_start: str  # ISO date
    period_end: str
    project_count: int
    median_duration_days: float
    mean_duration_days: float
    reform_in_effect: bool


class ReformTimeSeriesResult(TypedDict):
    """Time series of duration metrics around a reform's effective date."""

    reform_id: str
    reform_name: str
    jurisdiction: str
    stage_measured: str
    time_series: list[ReformTimeSeriesPoint]
    trend_before: float  # slope in days/month
    trend_after: float
    structural_break_detected: bool
    measured_at: str


# ---------------------------------------------------------------------------
# Single reform impact
# ---------------------------------------------------------------------------


def measure_reform_impact(
    db: Session,
    reform_id: UUID,
    *,
    stage: str = "entitlement",
    buffer_days: int | None = None,
) -> ReformImpactResult:
    """Measure the impact of a single policy reform on project timelines.

    Compares stage durations for projects that went through the relevant
    stage before vs. after the reform's effective date (with a buffer
    period excluded). Uses the appropriate statistical test based on data
    normality.

    Args:
        db: SQLAlchemy session.
        reform_id: UUID of the PolicyReform to evaluate.
        stage: Pipeline stage to measure (default "entitlement").
        buffer_days: Days after effective_date to exclude (transition
            period). If None, uses the reform's implementation_buffer_days.

    Returns:
        ReformImpactResult with statistical test results and cost
        estimates.

    Raises:
        ValueError: If the reform is not found or has no effective date.
    """
    reform = db.get(PolicyReform, reform_id)
    if reform is None:
        raise ValueError(f"PolicyReform {reform_id} not found.")
    if reform.effective_date is None:
        raise ValueError(f"Reform {reform.reform_name} has no effective_date.")

    buffer = buffer_days if buffer_days is not None else reform.implementation_buffer_days
    cutoff_date = reform.effective_date + timedelta(days=buffer)

    # Collect pre-reform durations
    pre_projects = _get_pre_reform_projects(db, reform, stage)
    pre_durations = _extract_durations(pre_projects, stage)

    # Collect post-reform durations
    post_projects = _get_post_reform_projects(db, reform, stage, cutoff_date)
    post_durations = _extract_durations(post_projects, stage)

    caveats: list[str] = []

    # Check minimum sample sizes
    if len(pre_durations) < 2:
        caveats.append(
            f"Only {len(pre_durations)} pre-reform project(s) with data; "
            f"results may not be reliable."
        )
    if len(post_durations) < 2:
        caveats.append(
            f"Only {len(post_durations)} post-reform project(s) with data; "
            f"results may not be reliable."
        )

    # Compute basic metrics
    pre_median = float(np.median(pre_durations)) if pre_durations else 0.0
    post_median = float(np.median(post_durations)) if post_durations else 0.0
    days_saved = pre_median - post_median
    pct_improvement = (
        (days_saved / pre_median * 100.0) if pre_median > 0 else 0.0
    )

    # Statistical testing
    if len(pre_durations) >= 2 and len(post_durations) >= 2:
        test_result = select_and_run_test(
            pre_durations, post_durations, alpha=0.05
        )
        test_used = test_result["test_used"]
        result_data = test_result["result"]
        p_value = result_data["p_value"]
        is_sig = result_data["significant"]

        if test_used == "ttest":
            effect_size = result_data.get("cohens_d", 0.0)
            ci = result_data.get("confidence_interval_diff", (0.0, 0.0))
        else:
            effect_size = result_data.get("rank_biserial_r", 0.0)
            # Approximate CI from pre/post
            ci = _bootstrap_ci_diff(pre_durations, post_durations)

        # Interpret effect size
        abs_es = abs(effect_size)
        if abs_es < 0.2:
            effect_interp = "negligible"
        elif abs_es < 0.5:
            effect_interp = "small"
        elif abs_es < 0.8:
            effect_interp = "medium"
        else:
            effect_interp = "large"
    else:
        test_used = "insufficient_data"
        p_value = 1.0
        is_sig = False
        effect_size = 0.0
        effect_interp = "insufficient_data"
        ci = (0.0, 0.0)
        caveats.append("Insufficient data for statistical testing.")

    # Cost savings estimate
    national = _load_national_benchmarks()
    holding_costs = national.get("holding_costs", {})
    daily_cost = float(
        holding_costs.get(f"daily_per_unit_during_{stage}", 20)
    )
    avg_units = _average_units(pre_projects + post_projects)
    cost_per_project = days_saved * daily_cost * avg_units
    total_cost_savings = cost_per_project * len(post_durations)

    # Units enabled: count projects that were stalled/abandoned pre-reform
    # and comparable projects succeeding post-reform
    abandoned_pre = get_abandoned_projects(
        db,
        reform.jurisdiction,
        abandoned_before=reform.effective_date,
    )
    units_enabled = sum(
        p.total_units or 0
        for p in abandoned_pre
        if _project_in_stage(p, stage)
    )

    # Stall rate change
    pre_stall_rate = _stall_rate(pre_projects, stage)
    post_stall_rate = _stall_rate(post_projects, stage)
    stall_change = post_stall_rate - pre_stall_rate

    # Projects unblocked (completed post-reform that wouldn't have under old timing)
    projects_unblocked = sum(
        1
        for d in post_durations
        if d < pre_median * 0.85  # significantly faster
    )

    # Confidence level
    conf_level = _determine_confidence(
        len(pre_durations), len(post_durations), is_sig, effect_interp
    )

    return ReformImpactResult(
        reform_id=str(reform.reform_id),
        reform_name=reform.reform_name,
        jurisdiction=reform.jurisdiction,
        reform_type=reform.reform_type.value,
        effective_date=(
            reform.effective_date.isoformat()
            if reform.effective_date
            else None
        ),
        pre_reform_n=len(pre_durations),
        post_reform_n=len(post_durations),
        pre_reform_median_days=round(pre_median, 1),
        post_reform_median_days=round(post_median, 1),
        days_saved_per_project=round(days_saved, 1),
        percent_improvement=round(pct_improvement, 1),
        test_used=test_used,
        p_value=round(p_value, 6),
        is_significant=is_sig,
        effect_size=round(effect_size, 3),
        effect_interpretation=effect_interp,
        confidence_interval_days_saved=(round(ci[0], 1), round(ci[1], 1)),
        total_cost_savings=round(total_cost_savings, 2),
        units_enabled=units_enabled,
        projects_unblocked=projects_unblocked,
        stall_rate_change=round(stall_change, 3),
        confidence_level=conf_level.value,
        caveats=caveats,
        measured_at=datetime.utcnow().isoformat(),
    )


def measure_reform_impact_and_persist(
    db: Session,
    reform_id: UUID,
    **kwargs,
) -> ReformImpactResult:
    """Measure reform impact and write results back to the PolicyReform.

    Args:
        db: SQLAlchemy session.
        reform_id: UUID of the PolicyReform.
        **kwargs: Additional arguments passed to measure_reform_impact.

    Returns:
        ReformImpactResult.
    """
    result = measure_reform_impact(db, reform_id, **kwargs)

    reform = db.get(PolicyReform, reform_id)
    if reform:
        reform.projects_pre_reform = result["pre_reform_n"]
        reform.projects_post_reform = result["post_reform_n"]
        reform.pre_reform_median_days = (
            int(result["pre_reform_median_days"])
            if result["pre_reform_median_days"]
            else None
        )
        reform.post_reform_median_days = (
            int(result["post_reform_median_days"])
            if result["post_reform_median_days"]
            else None
        )
        reform.days_saved_per_project = (
            int(result["days_saved_per_project"])
            if result["days_saved_per_project"]
            else None
        )
        reform.percent_improvement = result["percent_improvement"]
        reform.statistical_significance_p_value = result["p_value"]
        reform.confidence_level = ConfidenceLevel(result["confidence_level"])
        reform.total_cost_savings = result["total_cost_savings"]
        reform.units_enabled = result["units_enabled"]
        reform.projects_no_longer_delayed = result["projects_unblocked"]
        reform.impact_last_measured = date.today()

        db.commit()
        logger.info(
            "Persisted impact measurement for reform %s (%s).",
            reform.reform_name,
            reform.jurisdiction,
        )

    return result


# ---------------------------------------------------------------------------
# Multi-reform comparison
# ---------------------------------------------------------------------------


def compare_reforms_in_jurisdiction(
    db: Session,
    jurisdiction: str,
    *,
    stage: str = "entitlement",
) -> MultiReformComparisonResult:
    """Compare impacts of all reforms in a jurisdiction.

    Args:
        db: SQLAlchemy session.
        jurisdiction: Jurisdiction to analyze.
        stage: Pipeline stage to measure.

    Returns:
        MultiReformComparisonResult with ranked reform impacts.
    """
    stmt = select(PolicyReform).where(
        PolicyReform.jurisdiction == jurisdiction,
        PolicyReform.effective_date.isnot(None),
    )
    reforms = list(db.scalars(stmt).all())

    results: list[ReformImpactResult] = []
    for reform in reforms:
        try:
            result = measure_reform_impact(
                db, reform.reform_id, stage=stage
            )
            results.append(result)
        except Exception:
            logger.exception(
                "Failed to measure reform %s.", reform.reform_name
            )

    # Sort by days saved descending
    results.sort(key=lambda r: r["days_saved_per_project"], reverse=True)

    most_impactful = results[0]["reform_name"] if results else None
    total_days = sum(r["days_saved_per_project"] for r in results)
    total_cost = sum(r["total_cost_savings"] for r in results)
    total_units = sum(r["units_enabled"] for r in results)

    return MultiReformComparisonResult(
        jurisdiction=jurisdiction,
        reforms_analyzed=len(results),
        reform_results=results,
        most_impactful_reform=most_impactful,
        total_days_saved_all_reforms=round(total_days, 1),
        total_cost_savings_all_reforms=round(total_cost, 2),
        total_units_enabled=total_units,
        measured_at=datetime.utcnow().isoformat(),
    )


# ---------------------------------------------------------------------------
# Time series analysis
# ---------------------------------------------------------------------------


def build_reform_time_series(
    db: Session,
    reform_id: UUID,
    *,
    stage: str = "entitlement",
    period_months: int = 6,
    lookback_periods: int = 4,
    lookahead_periods: int = 4,
) -> ReformTimeSeriesResult:
    """Build a time series of stage durations around a reform's effective date.

    Divides the timeline into equal periods before and after the reform
    and computes median/mean durations for each period.

    Args:
        db: SQLAlchemy session.
        reform_id: UUID of the PolicyReform.
        stage: Pipeline stage to measure.
        period_months: Length of each time bucket in months.
        lookback_periods: Number of periods before the reform.
        lookahead_periods: Number of periods after the reform.

    Returns:
        ReformTimeSeriesResult with time series data points and trend
        estimates.
    """
    reform = db.get(PolicyReform, reform_id)
    if reform is None:
        raise ValueError(f"PolicyReform {reform_id} not found.")
    if reform.effective_date is None:
        raise ValueError(f"Reform {reform.reform_name} has no effective_date.")

    effective = reform.effective_date
    period_days = period_months * 30  # Approximate

    time_points: list[ReformTimeSeriesPoint] = []
    pre_medians: list[float] = []
    post_medians: list[float] = []

    # Build periods
    for i in range(-lookback_periods, lookahead_periods + 1):
        if i < 0:
            period_start = effective + timedelta(days=i * period_days)
            period_end = effective + timedelta(days=(i + 1) * period_days)
            reform_active = False
        elif i == 0:
            period_start = effective
            period_end = effective + timedelta(days=period_days)
            reform_active = True
        else:
            period_start = effective + timedelta(days=i * period_days)
            period_end = effective + timedelta(days=(i + 1) * period_days)
            reform_active = True

        # Get projects that completed the stage during this period
        projects = _get_projects_completing_stage_in_window(
            db, reform.jurisdiction, stage, period_start, period_end
        )
        durations = _extract_durations(projects, stage)

        if durations:
            med = float(np.median(durations))
            mean = float(np.mean(durations))
        else:
            med = 0.0
            mean = 0.0

        time_points.append(
            ReformTimeSeriesPoint(
                period_start=period_start.isoformat(),
                period_end=period_end.isoformat(),
                project_count=len(durations),
                median_duration_days=round(med, 1),
                mean_duration_days=round(mean, 1),
                reform_in_effect=reform_active,
            )
        )

        if not reform_active and med > 0:
            pre_medians.append(med)
        elif reform_active and med > 0:
            post_medians.append(med)

    # Compute trends (simple slope via least squares)
    trend_before = _compute_slope(pre_medians)
    trend_after = _compute_slope(post_medians)

    # Structural break: significant difference in means pre vs post
    structural_break = False
    if len(pre_medians) >= 2 and len(post_medians) >= 2:
        try:
            test_result = independent_ttest(pre_medians, post_medians, alpha=0.10)
            structural_break = test_result["significant"]
        except ValueError:
            pass

    return ReformTimeSeriesResult(
        reform_id=str(reform.reform_id),
        reform_name=reform.reform_name,
        jurisdiction=reform.jurisdiction,
        stage_measured=stage,
        time_series=time_points,
        trend_before=round(trend_before, 2),
        trend_after=round(trend_after, 2),
        structural_break_detected=structural_break,
        measured_at=datetime.utcnow().isoformat(),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_pre_reform_projects(
    db: Session,
    reform: PolicyReform,
    stage: str,
) -> list[Project]:
    """Get projects that completed the given stage before the reform."""
    stage_complete_attr = f"{stage}_complete"

    stmt = select(Project).where(
        Project.jurisdiction == reform.jurisdiction,
        getattr(Project, stage_complete_attr).isnot(None),
        getattr(Project, stage_complete_attr) < reform.effective_date,
    )
    return list(db.scalars(stmt).all())


def _get_post_reform_projects(
    db: Session,
    reform: PolicyReform,
    stage: str,
    cutoff_date: date,
) -> list[Project]:
    """Get projects that started the given stage after the buffer period."""
    stage_start_attr = f"{stage}_start"

    stmt = select(Project).where(
        Project.jurisdiction == reform.jurisdiction,
        getattr(Project, stage_start_attr).isnot(None),
        getattr(Project, stage_start_attr) >= cutoff_date,
    )
    return list(db.scalars(stmt).all())


def _get_projects_completing_stage_in_window(
    db: Session,
    jurisdiction: str,
    stage: str,
    window_start: date,
    window_end: date,
) -> list[Project]:
    """Get projects that completed a stage within a date window."""
    stage_complete_attr = f"{stage}_complete"

    stmt = select(Project).where(
        Project.jurisdiction == jurisdiction,
        getattr(Project, stage_complete_attr).isnot(None),
        getattr(Project, stage_complete_attr) >= window_start,
        getattr(Project, stage_complete_attr) <= window_end,
    )
    return list(db.scalars(stmt).all())


def _extract_durations(
    projects: list[Project],
    stage: str,
) -> list[float]:
    """Extract non-null stage durations from a list of projects."""
    attr = f"{stage}_duration_days"
    return [
        float(getattr(p, attr))
        for p in projects
        if getattr(p, attr, None) is not None
    ]


def _average_units(projects: list[Project]) -> float:
    """Average total_units across projects, defaulting to 50."""
    units = [p.total_units for p in projects if p.total_units and p.total_units > 0]
    return float(np.mean(units)) if units else 50.0


def _stall_rate(projects: list[Project], stage: str) -> float:
    """Fraction of projects in a stage that are stalled or abandoned."""
    in_stage = [
        p for p in projects
        if p.current_stage.value == stage
        or p.current_stage in (PipelineStage.STALLED, PipelineStage.ABANDONED)
    ]
    stalled = [
        p for p in in_stage
        if p.current_stage in (PipelineStage.STALLED, PipelineStage.ABANDONED)
    ]
    return len(stalled) / max(1, len(in_stage))


def _project_in_stage(project: Project, stage: str) -> bool:
    """Check if a project was last active in a given stage."""
    # Projects that were abandoned may have stage data hinting at their last stage
    if project.current_stage == PipelineStage.ABANDONED:
        # Check if the stage start was populated but not completed
        start_attr = f"{stage}_start"
        complete_attr = f"{stage}_complete"
        started = getattr(project, start_attr, None) is not None
        completed = getattr(project, complete_attr, None) is not None
        return started and not completed
    return project.current_stage.value == stage


def _bootstrap_ci_diff(
    pre: list[float],
    post: list[float],
    n_bootstrap: int = 1000,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Bootstrap confidence interval for the difference in medians."""
    rng = np.random.default_rng(42)
    pre_arr = np.array(pre, dtype=float)
    post_arr = np.array(post, dtype=float)

    diffs: list[float] = []
    for _ in range(n_bootstrap):
        pre_sample = rng.choice(pre_arr, size=len(pre_arr), replace=True)
        post_sample = rng.choice(post_arr, size=len(post_arr), replace=True)
        diffs.append(float(np.median(pre_sample) - np.median(post_sample)))

    alpha = 1 - confidence
    lower = float(np.percentile(diffs, alpha / 2 * 100))
    upper = float(np.percentile(diffs, (1 - alpha / 2) * 100))
    return (round(lower, 1), round(upper, 1))


def _determine_confidence(
    n_pre: int,
    n_post: int,
    is_significant: bool,
    effect_interp: str,
) -> ConfidenceLevel:
    """Determine confidence level from sample sizes and statistical results."""
    min_n = min(n_pre, n_post)

    if min_n >= 15 and is_significant and effect_interp in ("medium", "large"):
        return ConfidenceLevel.HIGH
    elif min_n >= 5 and (is_significant or effect_interp in ("small", "medium", "large")):
        return ConfidenceLevel.MODERATE
    else:
        return ConfidenceLevel.LOW


def _compute_slope(values: list[float]) -> float:
    """Compute simple linear slope over an ordered list of values."""
    if len(values) < 2:
        return 0.0
    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)
    # Least squares: slope = cov(x,y) / var(x)
    slope = float(np.polyfit(x, y, 1)[0])
    return slope
