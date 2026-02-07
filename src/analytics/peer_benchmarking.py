"""Peer group benchmarking for affordable housing projects.

Identifies comparable project cohorts based on jurisdiction, unit count,
building type, and AMI mix, then computes benchmark statistics used by
the timeline prediction and health assessment modules.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TypedDict
from uuid import UUID

import numpy as np
import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.database.queries import query_similar_projects
from src.models.enums import AMIMixCategory, BuildingType, PipelineStage
from src.models.peer_group import PeerGroup
from src.models.project import Project

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed results
# ---------------------------------------------------------------------------

# Ordered pipeline stages used for duration calculations
_ACTIVE_STAGES: list[str] = [
    "concept",
    "pre_development",
    "entitlement",
    "financing",
    "construction",
    "lease_up",
]


class StageBenchmark(TypedDict):
    """Duration benchmarks for a single pipeline stage."""

    stage: str
    median_days: float
    mean_days: float
    p25_days: float
    p75_days: float
    p90_days: float
    std_days: float
    sample_size: int


class PeerBenchmarkResult(TypedDict):
    """Complete peer benchmark result for a project or jurisdiction."""

    peer_group_id: UUID | None
    peer_group_name: str
    project_count: int
    stage_benchmarks: dict[str, StageBenchmark]
    median_total_duration_days: float | None
    median_cost_per_unit: float | None
    p25_cost_per_unit: float | None
    p75_cost_per_unit: float | None
    computed_at: str


class PeerComparisonResult(TypedDict):
    """How a single project compares to its peer group."""

    project_id: str
    project_name: str
    peer_group_name: str
    stage_comparisons: dict[str, StageComparisonDetail]
    overall_percentile: float | None
    cost_percentile: float | None
    faster_than_peers: bool
    cheaper_than_peers: bool


class StageComparisonDetail(TypedDict):
    """Per-stage comparison metrics."""

    actual_days: int | None
    peer_median_days: float
    delta_days: float | None
    percentile: float | None
    status: str  # "faster", "on_pace", "slower"


# ---------------------------------------------------------------------------
# National benchmarks loader
# ---------------------------------------------------------------------------

_national_benchmarks_cache: dict | None = None


def _load_national_benchmarks() -> dict:
    """Load national benchmark data from YAML config, with caching."""
    global _national_benchmarks_cache
    if _national_benchmarks_cache is not None:
        return _national_benchmarks_cache

    try:
        from config.settings import get_settings

        settings = get_settings()
        benchmarks_path = settings.project_root / "config" / "national_benchmarks.yaml"
        with open(benchmarks_path, "r") as f:
            data = yaml.safe_load(f)
        _national_benchmarks_cache = data.get("national_benchmarks", data)
        return _national_benchmarks_cache
    except Exception:
        logger.warning("Could not load national_benchmarks.yaml; using defaults.")
        _national_benchmarks_cache = _default_benchmarks()
        return _national_benchmarks_cache


def _default_benchmarks() -> dict:
    """Hardcoded fallback matching the YAML defaults."""
    return {
        "stage_durations": {
            "concept": {"median": 60, "p25": 30, "p75": 90, "p90": 120},
            "pre_development": {"median": 180, "p25": 120, "p75": 270, "p90": 365},
            "entitlement": {"median": 240, "p25": 150, "p75": 365, "p90": 540},
            "financing": {"median": 180, "p25": 120, "p75": 270, "p90": 365},
            "construction": {"median": 540, "p25": 365, "p75": 720, "p90": 900},
            "lease_up": {"median": 120, "p25": 60, "p75": 180, "p90": 270},
        },
        "total_timeline": {
            "median_days": 1320,
            "p25_days": 900,
            "p75_days": 1800,
        },
        "costs": {
            "national_median_per_unit": 350000,
            "national_p25_per_unit": 250000,
            "national_p75_per_unit": 475000,
        },
        "health_thresholds": {
            "on_track": 80,
            "at_risk": 60,
            "delayed": 40,
            "stalled": 0,
        },
    }


# ---------------------------------------------------------------------------
# Peer group identification
# ---------------------------------------------------------------------------


def find_peer_group(
    db: Session,
    project: Project,
) -> PeerGroup | None:
    """Find the best matching PeerGroup for a given project.

    Matches on jurisdiction first, then falls back to building type and
    unit count range.

    Args:
        db: SQLAlchemy session.
        project: The project to find peers for.

    Returns:
        Best-matching PeerGroup, or None if no group matches.
    """
    stmt = select(PeerGroup)

    # Prefer jurisdiction-specific groups
    if project.jurisdiction:
        stmt_j = stmt.where(PeerGroup.jurisdiction == project.jurisdiction)
        groups = list(db.scalars(stmt_j).all())
        if groups:
            return _best_match(groups, project)

    # Fall back to building-type + unit-range groups
    all_groups = list(db.scalars(stmt).all())
    return _best_match(all_groups, project) if all_groups else None


def _best_match(groups: list[PeerGroup], project: Project) -> PeerGroup | None:
    """Score peer groups against project attributes and return best match."""
    best_group = None
    best_score = -1

    for pg in groups:
        score = 0

        # Jurisdiction match
        if pg.jurisdiction and project.jurisdiction and pg.jurisdiction == project.jurisdiction:
            score += 3

        # Building type match
        if pg.building_type and project.building_type and pg.building_type == project.building_type:
            score += 2

        # Unit count range match
        if pg.unit_count_min is not None and pg.unit_count_max is not None:
            if pg.unit_count_min <= (project.total_units or 0) <= pg.unit_count_max:
                score += 2

        # AMI mix match
        if pg.ami_mix_category and project.total_units:
            project_ami_cat = _classify_ami_mix(project)
            if project_ami_cat and pg.ami_mix_category == project_ami_cat:
                score += 1

        if score > best_score:
            best_score = score
            best_group = pg

    return best_group


def _classify_ami_mix(project: Project) -> AMIMixCategory | None:
    """Classify a project's AMI targeting into a category."""
    total = project.affordable_units or project.total_units or 0
    if total == 0:
        return None

    deep = (project.ami_30_units or 0) + (project.ami_40_units or 0)
    senior = project.senior_units or 0

    if senior > 0 and senior >= total * 0.5:
        return AMIMixCategory.SENIOR
    if deep >= total * 0.5:
        return AMIMixCategory.DEEP_AFFORDABILITY
    if (project.market_rate_units or 0) > 0:
        return AMIMixCategory.MIXED_INCOME
    return AMIMixCategory.WORKFORCE


# ---------------------------------------------------------------------------
# Benchmark computation from peer data
# ---------------------------------------------------------------------------


def compute_peer_benchmarks(
    db: Session,
    *,
    jurisdiction: str | None = None,
    state: str | None = None,
    building_type: str | None = None,
    unit_count_range: tuple[float, float] | None = None,
    min_sample_size: int = 5,
) -> PeerBenchmarkResult:
    """Compute duration and cost benchmarks from peer projects.

    Queries completed or advanced-stage projects matching the given
    criteria and calculates percentile-based benchmarks for each
    pipeline stage.

    Args:
        db: SQLAlchemy session.
        jurisdiction: Filter by jurisdiction.
        state: Filter by state (used if jurisdiction yields too few).
        building_type: Filter by building type.
        unit_count_range: (min_units, max_units) filter.
        min_sample_size: Minimum peers required; falls back to national
            benchmarks if not met.

    Returns:
        PeerBenchmarkResult with per-stage and aggregate benchmarks.
    """
    peers = query_similar_projects(
        db,
        jurisdiction=jurisdiction,
        state=state,
        unit_count_range=unit_count_range,
        building_type=building_type,
        completed_only=True,
        limit=200,
    )

    # Fall back to state level if jurisdiction yields too few
    if len(peers) < min_sample_size and jurisdiction and state:
        logger.info(
            "Only %d peers in jurisdiction %s; expanding to state %s.",
            len(peers),
            jurisdiction,
            state,
        )
        peers = query_similar_projects(
            db,
            state=state,
            unit_count_range=unit_count_range,
            building_type=building_type,
            completed_only=True,
            limit=200,
        )

    use_national = len(peers) < min_sample_size

    stage_benchmarks: dict[str, StageBenchmark] = {}
    total_durations: list[float] = []
    cost_per_units: list[float] = []

    if use_national:
        logger.info(
            "Only %d peers found; supplementing with national benchmarks.",
            len(peers),
        )
        national = _load_national_benchmarks()
        stage_durations = national.get("stage_durations", {})

        for stage in _ACTIVE_STAGES:
            sd = stage_durations.get(stage, {})
            stage_benchmarks[stage] = StageBenchmark(
                stage=stage,
                median_days=float(sd.get("median", 0)),
                mean_days=float(sd.get("median", 0)),
                p25_days=float(sd.get("p25", 0)),
                p75_days=float(sd.get("p75", 0)),
                p90_days=float(sd.get("p90", 0)),
                std_days=0.0,
                sample_size=0,
            )

        total_timeline = national.get("total_timeline", {})
        median_total = float(total_timeline.get("median_days", 1320))
        costs_cfg = national.get("costs", {})
        median_cpu = float(costs_cfg.get("national_median_per_unit", 350000))

        return PeerBenchmarkResult(
            peer_group_id=None,
            peer_group_name="national_benchmarks",
            project_count=0,
            stage_benchmarks=stage_benchmarks,
            median_total_duration_days=median_total,
            median_cost_per_unit=median_cpu,
            p25_cost_per_unit=float(costs_cfg.get("national_p25_per_unit", 250000)),
            p75_cost_per_unit=float(costs_cfg.get("national_p75_per_unit", 475000)),
            computed_at=datetime.utcnow().isoformat(),
        )

    # Compute from actual peer data
    for stage in _ACTIVE_STAGES:
        durations = _extract_stage_durations(peers, stage)
        if len(durations) >= 2:
            arr = np.array(durations, dtype=float)
            stage_benchmarks[stage] = StageBenchmark(
                stage=stage,
                median_days=float(np.median(arr)),
                mean_days=float(np.mean(arr)),
                p25_days=float(np.percentile(arr, 25)),
                p75_days=float(np.percentile(arr, 75)),
                p90_days=float(np.percentile(arr, 90)),
                std_days=float(np.std(arr, ddof=1)),
                sample_size=len(durations),
            )
        else:
            # Use national for stages with insufficient data
            national = _load_national_benchmarks()
            sd = national.get("stage_durations", {}).get(stage, {})
            stage_benchmarks[stage] = StageBenchmark(
                stage=stage,
                median_days=float(sd.get("median", 0)),
                mean_days=float(sd.get("median", 0)),
                p25_days=float(sd.get("p25", 0)),
                p75_days=float(sd.get("p75", 0)),
                p90_days=float(sd.get("p90", 0)),
                std_days=0.0,
                sample_size=len(durations),
            )

    for p in peers:
        if p.total_elapsed_days is not None:
            total_durations.append(float(p.total_elapsed_days))
        if p.cost_per_unit is not None:
            cost_per_units.append(float(p.cost_per_unit))

    total_arr = np.array(total_durations, dtype=float) if total_durations else np.array([])
    cost_arr = np.array(cost_per_units, dtype=float) if cost_per_units else np.array([])

    group_name = _build_group_name(jurisdiction, state, building_type)

    return PeerBenchmarkResult(
        peer_group_id=None,
        peer_group_name=group_name,
        project_count=len(peers),
        stage_benchmarks=stage_benchmarks,
        median_total_duration_days=(
            float(np.median(total_arr)) if len(total_arr) > 0 else None
        ),
        median_cost_per_unit=(
            float(np.median(cost_arr)) if len(cost_arr) > 0 else None
        ),
        p25_cost_per_unit=(
            float(np.percentile(cost_arr, 25)) if len(cost_arr) > 0 else None
        ),
        p75_cost_per_unit=(
            float(np.percentile(cost_arr, 75)) if len(cost_arr) > 0 else None
        ),
        computed_at=datetime.utcnow().isoformat(),
    )


def compare_project_to_peers(
    db: Session,
    project: Project,
    peer_benchmark: PeerBenchmarkResult | None = None,
) -> PeerComparisonResult:
    """Compare a project's actual durations and costs to peer benchmarks.

    Args:
        db: SQLAlchemy session.
        project: The project to evaluate.
        peer_benchmark: Pre-computed peer benchmarks. If None, will be
            computed automatically.

    Returns:
        PeerComparisonResult with per-stage comparisons and percentile
        rankings.
    """
    if peer_benchmark is None:
        peer_benchmark = compute_peer_benchmarks(
            db,
            jurisdiction=project.jurisdiction,
            state=project.state,
            building_type=(
                project.building_type.value if project.building_type else None
            ),
            unit_count_range=(
                _unit_range(project.total_units) if project.total_units else None
            ),
        )

    stage_comparisons: dict[str, StageComparisonDetail] = {}
    deltas: list[float] = []

    for stage in _ACTIVE_STAGES:
        bench = peer_benchmark["stage_benchmarks"].get(stage)
        if bench is None:
            continue

        actual = project.get_stage_duration(stage)
        peer_median = bench["median_days"]

        if actual is not None and peer_median > 0:
            delta = float(actual) - peer_median
            deltas.append(delta)

            # Compute percentile using normal approximation from bench stats
            if bench["std_days"] > 0:
                from scipy.stats import norm

                z = (float(actual) - bench["mean_days"]) / bench["std_days"]
                pctl = float(norm.cdf(z) * 100)
            else:
                pctl = 50.0 if actual <= peer_median else 75.0

            if delta <= -peer_median * 0.1:
                status = "faster"
            elif delta >= peer_median * 0.15:
                status = "slower"
            else:
                status = "on_pace"
        else:
            delta = None
            pctl = None
            status = "no_data"

        stage_comparisons[stage] = StageComparisonDetail(
            actual_days=actual,
            peer_median_days=peer_median,
            delta_days=delta,
            percentile=pctl,
            status=status,
        )

    # Overall percentile from total elapsed
    overall_pctl = None
    if project.total_elapsed_days and peer_benchmark["median_total_duration_days"]:
        if peer_benchmark["median_total_duration_days"] > 0:
            ratio = project.total_elapsed_days / peer_benchmark["median_total_duration_days"]
            overall_pctl = min(100.0, ratio * 50.0)

    # Cost percentile
    cost_pctl = None
    if project.cost_per_unit and peer_benchmark["median_cost_per_unit"]:
        if peer_benchmark["median_cost_per_unit"] > 0:
            ratio = float(project.cost_per_unit) / peer_benchmark["median_cost_per_unit"]
            cost_pctl = min(100.0, ratio * 50.0)

    avg_delta = np.mean(deltas) if deltas else 0.0

    return PeerComparisonResult(
        project_id=str(project.project_id),
        project_name=project.project_name,
        peer_group_name=peer_benchmark["peer_group_name"],
        stage_comparisons=stage_comparisons,
        overall_percentile=overall_pctl,
        cost_percentile=cost_pctl,
        faster_than_peers=bool(avg_delta < 0),
        cheaper_than_peers=bool(
            cost_pctl is not None and cost_pctl < 50.0
        ),
    )


def refresh_peer_group_stats(
    db: Session,
    peer_group_id: UUID,
) -> PeerGroup:
    """Recalculate benchmark stats for a saved PeerGroup and persist them.

    Queries matching projects, computes medians and percentiles, and
    updates the PeerGroup record in the database.

    Args:
        db: SQLAlchemy session.
        peer_group_id: ID of the PeerGroup to refresh.

    Returns:
        Updated PeerGroup instance.

    Raises:
        ValueError: If the PeerGroup does not exist.
    """
    pg = db.get(PeerGroup, peer_group_id)
    if pg is None:
        raise ValueError(f"PeerGroup {peer_group_id} not found.")

    peers = query_similar_projects(
        db,
        jurisdiction=pg.jurisdiction,
        unit_count_range=(
            (float(pg.unit_count_min), float(pg.unit_count_max))
            if pg.unit_count_min is not None and pg.unit_count_max is not None
            else None
        ),
        building_type=pg.building_type.value if pg.building_type else None,
        completed_only=True,
        limit=500,
    )

    pg.project_count = len(peers)

    # Stage duration medians
    for stage, attr in [
        ("concept", "median_concept_duration"),
        ("pre_development", "median_pre_dev_duration"),
        ("entitlement", "median_entitlement_duration"),
        ("financing", "median_financing_duration"),
        ("construction", "median_construction_duration"),
    ]:
        durations = _extract_stage_durations(peers, stage)
        if durations:
            setattr(pg, attr, int(np.median(durations)))
        else:
            setattr(pg, attr, None)

    # Total duration
    totals = [p.total_elapsed_days for p in peers if p.total_elapsed_days is not None]
    pg.median_total_duration = int(np.median(totals)) if totals else None

    # Cost per unit
    cpus = [float(p.cost_per_unit) for p in peers if p.cost_per_unit is not None]
    if cpus:
        arr = np.array(cpus)
        pg.median_cost_per_unit = float(np.median(arr))
        pg.p25_cost_per_unit = float(np.percentile(arr, 25))
        pg.p75_cost_per_unit = float(np.percentile(arr, 75))
    else:
        pg.median_cost_per_unit = None
        pg.p25_cost_per_unit = None
        pg.p75_cost_per_unit = None

    pg.last_calculated = datetime.utcnow()
    db.commit()
    db.refresh(pg)

    logger.info(
        "Refreshed PeerGroup %s (%s) with %d projects.",
        pg.peer_group_id,
        pg.group_name,
        pg.project_count,
    )
    return pg


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _extract_stage_durations(
    projects: list[Project],
    stage: str,
) -> list[float]:
    """Extract non-null durations for a pipeline stage from project list."""
    attr = f"{stage}_duration_days"
    durations = []
    for p in projects:
        val = getattr(p, attr, None)
        if val is not None:
            durations.append(float(val))
    return durations


def _unit_range(total_units: int) -> tuple[float, float]:
    """Generate a +/- 50% unit count range for peer matching."""
    low = max(1, total_units * 0.5)
    high = total_units * 1.5
    return (low, high)


def _build_group_name(
    jurisdiction: str | None,
    state: str | None,
    building_type: str | None,
) -> str:
    """Construct a human-readable peer group label."""
    parts = []
    if jurisdiction:
        parts.append(jurisdiction)
    elif state:
        parts.append(f"state:{state}")
    if building_type:
        parts.append(building_type)
    return "_".join(parts) if parts else "all_projects"
