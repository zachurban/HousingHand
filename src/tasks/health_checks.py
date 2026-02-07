"""Celery tasks for periodic project health assessments."""

import logging
from datetime import date, datetime

from src.database.connection import get_session_factory
from src.models.enums import OverallHealth, PipelineStage
from src.models.project import Project
from src.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# Stages that need active health monitoring
ACTIVE_STAGES = [
    PipelineStage.CONCEPT,
    PipelineStage.PRE_DEVELOPMENT,
    PipelineStage.ENTITLEMENT,
    PipelineStage.FINANCING,
    PipelineStage.CONSTRUCTION,
    PipelineStage.LEASE_UP,
]


@celery_app.task(name="src.tasks.health_checks.run_health_checks")
def run_health_checks() -> dict:
    """Run health assessments on all active projects."""
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        projects = (
            db.query(Project)
            .filter(Project.current_stage.in_(ACTIVE_STAGES))
            .all()
        )

        checked = 0
        newly_at_risk = 0
        newly_stalled = 0

        for project in projects:
            try:
                old_health = project.overall_health
                _update_health(project)

                if (
                    old_health == OverallHealth.ON_TRACK
                    and project.overall_health in [OverallHealth.AT_RISK, OverallHealth.DELAYED]
                ):
                    newly_at_risk += 1

                if project.overall_health == OverallHealth.STALLED and old_health != OverallHealth.STALLED:
                    newly_stalled += 1

                checked += 1
            except Exception:
                logger.exception(f"Error checking health for {project.project_slug}")

        db.commit()

        result = {
            "total_active_projects": len(projects),
            "checked": checked,
            "newly_at_risk": newly_at_risk,
            "newly_stalled": newly_stalled,
            "timestamp": datetime.utcnow().isoformat(),
        }
        logger.info(f"Health checks complete: {result}")
        return result

    finally:
        db.close()


def _update_health(project: Project) -> None:
    """Update the health status and days-in-stage for a project."""
    # Update days in current stage
    if project.stage_entry_date:
        project.days_in_current_stage = (date.today() - project.stage_entry_date).days

    # Simple health heuristic based on days in stage vs benchmarks
    from config.settings import get_settings
    from pathlib import Path
    import yaml

    settings = get_settings()
    benchmarks_path = settings.project_root / "config" / "national_benchmarks.yaml"

    try:
        with open(benchmarks_path) as f:
            benchmarks = yaml.safe_load(f)
    except FileNotFoundError:
        benchmarks = None

    if benchmarks and project.days_in_current_stage is not None:
        stage_key = project.current_stage.value
        stage_benchmarks = (
            benchmarks.get("national_benchmarks", {})
            .get("stage_durations", {})
            .get(stage_key, {})
        )
        p90 = stage_benchmarks.get("p90")

        if p90:
            ratio = project.days_in_current_stage / p90
            if ratio < 0.5:
                project.overall_health = OverallHealth.ON_TRACK
                project.health_score = min(100, 100 - (ratio * 40))
            elif ratio < 0.8:
                project.overall_health = OverallHealth.ON_TRACK
                project.health_score = max(60, 100 - (ratio * 50))
            elif ratio < 1.0:
                project.overall_health = OverallHealth.AT_RISK
                project.health_score = max(40, 80 - (ratio * 40))
            elif ratio < 1.5:
                project.overall_health = OverallHealth.DELAYED
                project.health_score = max(20, 60 - (ratio * 30))
            else:
                project.overall_health = OverallHealth.STALLED
                project.health_score = max(0, 30 - (ratio * 10))
