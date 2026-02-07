"""Celery tasks for recalculating peer group benchmarks."""

import logging
from datetime import datetime

import numpy as np

from src.database.connection import get_session_factory
from src.models.peer_group import PeerGroup
from src.models.project import Project
from src.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="src.tasks.calculate_benchmarks.recalculate_all_benchmarks")
def recalculate_all_benchmarks() -> dict:
    """Recalculate statistics for all peer groups."""
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        peer_groups = db.query(PeerGroup).all()

        updated = 0
        for pg in peer_groups:
            try:
                _recalculate_peer_group(db, pg)
                updated += 1
            except Exception:
                logger.exception(f"Error recalculating peer group: {pg.group_name}")

        db.commit()
        result = {
            "total_groups": len(peer_groups),
            "updated": updated,
            "timestamp": datetime.utcnow().isoformat(),
        }
        logger.info(f"Benchmark recalculation complete: {result}")
        return result

    finally:
        db.close()


@celery_app.task(name="src.tasks.calculate_benchmarks.recalculate_peer_group")
def recalculate_peer_group(peer_group_id: str) -> dict:
    """Recalculate statistics for a single peer group."""
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        pg = db.get(PeerGroup, peer_group_id)
        if pg is None:
            return {"error": f"Peer group not found: {peer_group_id}"}

        _recalculate_peer_group(db, pg)
        db.commit()

        return {
            "peer_group_id": peer_group_id,
            "project_count": pg.project_count,
            "median_total_duration": pg.median_total_duration,
            "timestamp": datetime.utcnow().isoformat(),
        }
    finally:
        db.close()


def _recalculate_peer_group(db, pg: PeerGroup) -> None:
    """Recalculate benchmark stats for a peer group."""
    query = db.query(Project)

    if pg.jurisdiction:
        query = query.filter(Project.jurisdiction == pg.jurisdiction)
    if pg.unit_count_min is not None:
        query = query.filter(Project.total_units >= pg.unit_count_min)
    if pg.unit_count_max is not None:
        query = query.filter(Project.total_units <= pg.unit_count_max)
    if pg.building_type:
        query = query.filter(Project.building_type == pg.building_type)

    projects = query.all()
    pg.project_count = len(projects)

    if not projects:
        pg.last_calculated = datetime.utcnow()
        return

    def _safe_median(values):
        filtered = [v for v in values if v is not None and v > 0]
        return int(np.median(filtered)) if filtered else None

    pg.median_concept_duration = _safe_median(
        [p.concept_duration_days for p in projects]
    )
    pg.median_pre_dev_duration = _safe_median(
        [p.pre_development_duration_days for p in projects]
    )
    pg.median_entitlement_duration = _safe_median(
        [p.entitlement_duration_days for p in projects]
    )
    pg.median_financing_duration = _safe_median(
        [p.financing_duration_days for p in projects]
    )
    pg.median_construction_duration = _safe_median(
        [p.construction_duration_days for p in projects]
    )

    total_durations = [p.concept_to_co_days for p in projects if p.concept_to_co_days]
    if total_durations:
        pg.median_total_duration = int(np.median(total_durations))

    costs = [float(p.cost_per_unit) for p in projects if p.cost_per_unit]
    if costs:
        pg.median_cost_per_unit = float(np.median(costs))
        pg.p25_cost_per_unit = float(np.percentile(costs, 25))
        pg.p75_cost_per_unit = float(np.percentile(costs, 75))

    pg.last_calculated = datetime.utcnow()
