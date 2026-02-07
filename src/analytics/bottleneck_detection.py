"""Systemic bottleneck identification across jurisdictions.

Detects recurring friction patterns by aggregating project barriers,
stage durations, and stall rates across jurisdictions. Produces ranked
bottleneck reports that surface the highest-impact regulatory friction
topics and the pipeline stages where projects most commonly get stuck.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime
from typing import TypedDict

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.analytics.peer_benchmarking import (
    _ACTIVE_STAGES,
    _extract_stage_durations,
    _load_national_benchmarks,
)
from src.database.queries import (
    get_stalled_projects,
    query_projects,
)
from src.models.barrier import ProjectBarrier
from src.models.enums import BarrierStage, PipelineStage
from src.models.project import Project

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed results
# ---------------------------------------------------------------------------


class StageBottleneck(TypedDict):
    """Bottleneck summary for a single pipeline stage."""

    stage: str
    project_count: int
    median_days: float
    national_median_days: float
    excess_days: float
    excess_ratio: float  # actual / national median
    stalled_count: int
    stall_rate: float  # fraction of projects stalled in this stage
    top_friction_topics: list[FrictionTopicSummary]


class FrictionTopicSummary(TypedDict):
    """Summary of a friction topic's impact."""

    topic: str
    occurrence_count: int
    total_days_delayed: int
    total_cost_impact: float
    median_days_delayed: float
    affected_project_ids: list[str]
    jurisdictions: list[str]


class JurisdictionBottleneck(TypedDict):
    """Bottleneck analysis for a specific jurisdiction."""

    jurisdiction: str
    total_projects: int
    overall_friction_score: float
    stage_bottlenecks: list[StageBottleneck]
    top_friction_topics: list[FrictionTopicSummary]
    worst_stage: str | None
    estimated_excess_days_per_project: float
    estimated_excess_cost_per_project: float


class SystemicBottleneckReport(TypedDict):
    """Cross-jurisdiction bottleneck analysis."""

    total_jurisdictions_analyzed: int
    total_projects_analyzed: int
    jurisdiction_rankings: list[JurisdictionBottleneck]
    global_top_friction_topics: list[FrictionTopicSummary]
    global_worst_stages: list[StageBottleneck]
    generated_at: str


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


def detect_jurisdiction_bottlenecks(
    db: Session,
    jurisdiction: str,
    *,
    stall_threshold_days: int = 180,
) -> JurisdictionBottleneck:
    """Analyze bottlenecks for a single jurisdiction.

    Aggregates project barriers by stage and friction topic, compares
    stage durations to national medians, and identifies where projects
    are most commonly stalled or delayed.

    Args:
        db: SQLAlchemy session.
        jurisdiction: The jurisdiction to analyze.
        stall_threshold_days: Number of days beyond which a project in
            a stage is considered stalled.

    Returns:
        JurisdictionBottleneck with ranked stage bottlenecks and friction
        topic summaries.
    """
    projects = query_projects(db, jurisdiction=jurisdiction, limit=1000)
    if not projects:
        return _empty_jurisdiction_bottleneck(jurisdiction)

    national = _load_national_benchmarks()
    national_stages = national.get("stage_durations", {})
    holding_costs = national.get("holding_costs", {})

    # Barriers for this jurisdiction
    barriers = _get_jurisdiction_barriers(db, jurisdiction)
    friction_by_stage = _group_barriers_by_stage(barriers)
    friction_by_topic = _group_barriers_by_topic(barriers)

    stalled = get_stalled_projects(
        db, days_threshold=stall_threshold_days, jurisdiction=jurisdiction
    )
    stalled_by_stage = _count_by_stage(stalled)

    # Analyze each stage
    stage_bottlenecks: list[StageBottleneck] = []
    total_excess_days = 0.0

    for stage in _ACTIVE_STAGES:
        durations = _extract_stage_durations(projects, stage)
        nat_bench = national_stages.get(stage, {})
        nat_median = float(nat_bench.get("median", 0))

        if durations:
            arr = np.array(durations, dtype=float)
            median_days = float(np.median(arr))
        else:
            median_days = 0.0

        excess = max(0.0, median_days - nat_median) if nat_median > 0 else 0.0
        ratio = median_days / nat_median if nat_median > 0 else 1.0
        total_excess_days += excess

        stage_stalled = stalled_by_stage.get(stage, 0)
        # Count how many projects have been in this stage
        in_stage = sum(
            1 for p in projects if p.current_stage.value == stage
        )
        stall_rate = stage_stalled / in_stage if in_stage > 0 else 0.0

        # Top friction topics for this stage
        stage_friction = friction_by_stage.get(stage, [])
        top_topics = _summarize_friction_topics(stage_friction, top_n=5)

        stage_bottlenecks.append(
            StageBottleneck(
                stage=stage,
                project_count=len(durations),
                median_days=median_days,
                national_median_days=nat_median,
                excess_days=excess,
                excess_ratio=round(ratio, 2),
                stalled_count=stage_stalled,
                stall_rate=round(stall_rate, 3),
                top_friction_topics=top_topics,
            )
        )

    # Sort stages by excess ratio descending (worst first)
    stage_bottlenecks.sort(key=lambda s: s["excess_ratio"], reverse=True)
    worst_stage = stage_bottlenecks[0]["stage"] if stage_bottlenecks else None

    # Global friction topics for jurisdiction
    top_friction = _summarize_friction_topics(barriers, top_n=10)

    # Overall friction score: weighted average of excess ratios
    if stage_bottlenecks:
        ratios = [s["excess_ratio"] for s in stage_bottlenecks if s["project_count"] > 0]
        overall_friction = float(np.mean(ratios)) * 50.0 if ratios else 50.0
    else:
        overall_friction = 50.0

    # Estimated excess cost per project
    daily_holding = float(
        holding_costs.get("daily_per_unit_during_entitlement", 15)
    )
    avg_units = (
        np.mean([p.total_units for p in projects if p.total_units])
        if projects
        else 50
    )
    excess_cost = total_excess_days * daily_holding * avg_units

    return JurisdictionBottleneck(
        jurisdiction=jurisdiction,
        total_projects=len(projects),
        overall_friction_score=round(min(100.0, overall_friction), 1),
        stage_bottlenecks=stage_bottlenecks,
        top_friction_topics=top_friction,
        worst_stage=worst_stage,
        estimated_excess_days_per_project=round(
            total_excess_days / max(1, len(projects)), 1
        ),
        estimated_excess_cost_per_project=round(
            excess_cost / max(1, len(projects)), 2
        ),
    )


def detect_systemic_bottlenecks(
    db: Session,
    *,
    jurisdictions: list[str] | None = None,
    state: str | None = None,
    top_n_jurisdictions: int = 20,
    stall_threshold_days: int = 180,
) -> SystemicBottleneckReport:
    """Cross-jurisdiction systemic bottleneck analysis.

    Runs bottleneck detection across multiple jurisdictions and aggregates
    findings to reveal system-wide patterns.

    Args:
        db: SQLAlchemy session.
        jurisdictions: Specific jurisdictions to analyze. If None,
            discovers jurisdictions from the database.
        state: If provided and jurisdictions is None, limit to this state.
        top_n_jurisdictions: Max jurisdictions to include in results.
        stall_threshold_days: Stall threshold for per-jurisdiction analysis.

    Returns:
        SystemicBottleneckReport with ranked jurisdictions and global
        friction topic summaries.
    """
    if jurisdictions is None:
        jurisdictions = _discover_jurisdictions(db, state=state, limit=top_n_jurisdictions)

    jurisdiction_results: list[JurisdictionBottleneck] = []
    all_barriers: list[ProjectBarrier] = []
    total_projects = 0

    for jur in jurisdictions:
        try:
            result = detect_jurisdiction_bottlenecks(
                db, jur, stall_threshold_days=stall_threshold_days
            )
            jurisdiction_results.append(result)
            total_projects += result["total_projects"]

            # Collect barriers for global analysis
            jur_barriers = _get_jurisdiction_barriers(db, jur)
            all_barriers.extend(jur_barriers)
        except Exception:
            logger.exception("Failed bottleneck analysis for %s.", jur)

    # Rank jurisdictions by friction score descending (worst first)
    jurisdiction_results.sort(
        key=lambda j: j["overall_friction_score"], reverse=True
    )

    # Global friction topics
    global_topics = _summarize_friction_topics(all_barriers, top_n=15)

    # Global worst stages (aggregate across jurisdictions)
    global_stages = _aggregate_stage_bottlenecks(jurisdiction_results)

    return SystemicBottleneckReport(
        total_jurisdictions_analyzed=len(jurisdiction_results),
        total_projects_analyzed=total_projects,
        jurisdiction_rankings=jurisdiction_results[:top_n_jurisdictions],
        global_top_friction_topics=global_topics,
        global_worst_stages=global_stages,
        generated_at=datetime.utcnow().isoformat(),
    )


def identify_stage_chokepoints(
    db: Session,
    *,
    jurisdiction: str | None = None,
    state: str | None = None,
    min_projects: int = 3,
) -> list[StageBottleneck]:
    """Identify the specific pipeline stages acting as chokepoints.

    A chokepoint is defined as a stage where:
    - The median duration exceeds the national benchmark by > 25%, AND
    - At least min_projects have data for that stage.

    Args:
        db: SQLAlchemy session.
        jurisdiction: Optional jurisdiction filter.
        state: Optional state filter.
        min_projects: Minimum projects with data to consider a stage.

    Returns:
        List of StageBottleneck for stages qualifying as chokepoints,
        sorted by excess ratio descending.
    """
    projects = query_projects(
        db, jurisdiction=jurisdiction, state=state, limit=1000
    )
    national = _load_national_benchmarks().get("stage_durations", {})
    barriers = []
    if jurisdiction:
        barriers = _get_jurisdiction_barriers(db, jurisdiction)

    friction_by_stage = _group_barriers_by_stage(barriers)
    chokepoints: list[StageBottleneck] = []

    for stage in _ACTIVE_STAGES:
        durations = _extract_stage_durations(projects, stage)
        if len(durations) < min_projects:
            continue

        nat_bench = national.get(stage, {})
        nat_median = float(nat_bench.get("median", 0))
        if nat_median == 0:
            continue

        arr = np.array(durations, dtype=float)
        median_days = float(np.median(arr))
        excess_ratio = median_days / nat_median

        if excess_ratio > 1.25:
            stage_friction = friction_by_stage.get(stage, [])
            top_topics = _summarize_friction_topics(stage_friction, top_n=3)

            chokepoints.append(
                StageBottleneck(
                    stage=stage,
                    project_count=len(durations),
                    median_days=median_days,
                    national_median_days=nat_median,
                    excess_days=median_days - nat_median,
                    excess_ratio=round(excess_ratio, 2),
                    stalled_count=0,
                    stall_rate=0.0,
                    top_friction_topics=top_topics,
                )
            )

    chokepoints.sort(key=lambda c: c["excess_ratio"], reverse=True)
    return chokepoints


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_jurisdiction_barriers(
    db: Session,
    jurisdiction: str,
) -> list[ProjectBarrier]:
    """Fetch all barriers for projects in a jurisdiction."""
    stmt = (
        select(ProjectBarrier)
        .join(Project, ProjectBarrier.project_id == Project.project_id)
        .where(Project.jurisdiction == jurisdiction)
    )
    return list(db.scalars(stmt).all())


def _group_barriers_by_stage(
    barriers: list[ProjectBarrier],
) -> dict[str, list[ProjectBarrier]]:
    """Group barriers by the stage in which they were encountered."""
    grouped: dict[str, list[ProjectBarrier]] = defaultdict(list)
    for b in barriers:
        if b.stage_encountered is not None:
            grouped[b.stage_encountered.value].append(b)
        else:
            grouped["unknown"].append(b)
    return grouped


def _group_barriers_by_topic(
    barriers: list[ProjectBarrier],
) -> dict[str, list[ProjectBarrier]]:
    """Group barriers by their barrier_type (friction topic)."""
    grouped: dict[str, list[ProjectBarrier]] = defaultdict(list)
    for b in barriers:
        grouped[b.barrier_type].append(b)
    return grouped


def _summarize_friction_topics(
    barriers: list[ProjectBarrier],
    top_n: int = 10,
) -> list[FrictionTopicSummary]:
    """Aggregate barriers by topic and produce ranked summaries."""
    by_topic = _group_barriers_by_topic(barriers)
    summaries: list[FrictionTopicSummary] = []

    for topic, topic_barriers in by_topic.items():
        days_list = [b.days_delayed for b in topic_barriers if b.days_delayed]
        cost_list = [
            float(b.cost_impact) for b in topic_barriers if b.cost_impact
        ]
        project_ids = list(
            {str(b.project_id) for b in topic_barriers}
        )
        jurisdictions = list(
            {b.jurisdiction for b in topic_barriers if b.jurisdiction}
        )

        summaries.append(
            FrictionTopicSummary(
                topic=topic,
                occurrence_count=len(topic_barriers),
                total_days_delayed=sum(days_list),
                total_cost_impact=sum(cost_list),
                median_days_delayed=(
                    float(np.median(days_list)) if days_list else 0.0
                ),
                affected_project_ids=project_ids,
                jurisdictions=jurisdictions,
            )
        )

    # Rank by total days delayed descending
    summaries.sort(key=lambda s: s["total_days_delayed"], reverse=True)
    return summaries[:top_n]


def _count_by_stage(projects: list[Project]) -> dict[str, int]:
    """Count projects by their current stage."""
    counts: dict[str, int] = defaultdict(int)
    for p in projects:
        counts[p.current_stage.value] += 1
    return counts


def _discover_jurisdictions(
    db: Session,
    *,
    state: str | None = None,
    limit: int = 50,
) -> list[str]:
    """Discover jurisdictions with the most projects."""
    stmt = (
        select(
            Project.jurisdiction,
            func.count(Project.project_id).label("cnt"),
        )
        .where(Project.jurisdiction.isnot(None))
        .group_by(Project.jurisdiction)
        .order_by(func.count(Project.project_id).desc())
        .limit(limit)
    )
    if state:
        stmt = stmt.where(Project.state == state)

    rows = db.execute(stmt).all()
    return [row.jurisdiction for row in rows if row.jurisdiction]


def _aggregate_stage_bottlenecks(
    jurisdiction_results: list[JurisdictionBottleneck],
) -> list[StageBottleneck]:
    """Aggregate stage bottleneck data across jurisdictions.

    Computes a weighted-average excess ratio per stage across all
    analyzed jurisdictions.
    """
    stage_data: dict[str, list[tuple[float, int]]] = defaultdict(list)

    for jur in jurisdiction_results:
        for sb in jur["stage_bottlenecks"]:
            if sb["project_count"] > 0:
                stage_data[sb["stage"]].append(
                    (sb["excess_ratio"], sb["project_count"])
                )

    global_stages: list[StageBottleneck] = []

    for stage in _ACTIVE_STAGES:
        entries = stage_data.get(stage, [])
        if not entries:
            continue

        ratios = [e[0] for e in entries]
        counts = [e[1] for e in entries]
        total_count = sum(counts)

        # Weighted average excess ratio
        weighted_ratio = float(
            np.average(ratios, weights=counts)
        )

        # Weighted average median days
        medians = [e[0] for e in entries]  # approximation
        national = _load_national_benchmarks().get("stage_durations", {})
        nat_median = float(national.get(stage, {}).get("median", 0))

        global_stages.append(
            StageBottleneck(
                stage=stage,
                project_count=total_count,
                median_days=weighted_ratio * nat_median if nat_median else 0.0,
                national_median_days=nat_median,
                excess_days=max(0.0, (weighted_ratio - 1.0) * nat_median),
                excess_ratio=round(weighted_ratio, 2),
                stalled_count=0,
                stall_rate=0.0,
                top_friction_topics=[],
            )
        )

    global_stages.sort(key=lambda s: s["excess_ratio"], reverse=True)
    return global_stages


def _empty_jurisdiction_bottleneck(jurisdiction: str) -> JurisdictionBottleneck:
    """Return an empty bottleneck result when no projects are found."""
    return JurisdictionBottleneck(
        jurisdiction=jurisdiction,
        total_projects=0,
        overall_friction_score=0.0,
        stage_bottlenecks=[],
        top_friction_topics=[],
        worst_stage=None,
        estimated_excess_days_per_project=0.0,
        estimated_excess_cost_per_project=0.0,
    )
