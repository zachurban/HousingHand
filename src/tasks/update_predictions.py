"""Celery tasks for refreshing timeline predictions."""

import logging
from datetime import datetime

from src.database.connection import get_session_factory
from src.models.enums import PipelineStage
from src.models.project import Project
from src.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# Stages where predictions are relevant
PREDICTABLE_STAGES = [
    PipelineStage.CONCEPT,
    PipelineStage.PRE_DEVELOPMENT,
    PipelineStage.ENTITLEMENT,
    PipelineStage.FINANCING,
    PipelineStage.CONSTRUCTION,
]


@celery_app.task(name="src.tasks.update_predictions.update_all_predictions")
def update_all_predictions() -> dict:
    """Refresh timeline predictions for all active projects."""
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        projects = (
            db.query(Project)
            .filter(Project.current_stage.in_(PREDICTABLE_STAGES))
            .all()
        )

        updated = 0
        errors = 0

        for project in projects:
            try:
                _update_single_prediction(db, project)
                updated += 1
            except Exception:
                logger.exception(
                    f"Error updating prediction for {project.project_slug}"
                )
                errors += 1

        db.commit()
        result = {
            "total_projects": len(projects),
            "updated": updated,
            "errors": errors,
            "timestamp": datetime.utcnow().isoformat(),
        }
        logger.info(f"Prediction update complete: {result}")
        return result

    finally:
        db.close()


@celery_app.task(name="src.tasks.update_predictions.update_project_prediction")
def update_project_prediction(project_id: str) -> dict:
    """Refresh timeline prediction for a single project."""
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        project = db.get(Project, project_id)
        if project is None:
            return {"error": f"Project not found: {project_id}"}

        _update_single_prediction(db, project)
        db.commit()

        return {
            "project_id": project_id,
            "predicted_co": project.predicted_co.isoformat() if project.predicted_co else None,
            "confidence": project.prediction_confidence,
            "timestamp": datetime.utcnow().isoformat(),
        }
    finally:
        db.close()


def _update_single_prediction(db, project: Project) -> None:
    """Update prediction fields on a single project (internal helper)."""
    from src.analytics.timeline_prediction import predict_project_timeline

    result = predict_project_timeline(db, project)

    if "error" not in result:
        timeline = result.get("predicted_timeline", {})

        # Update prediction dates on project based on current stage
        # Convert months to approximate dates from now
        from datetime import date, timedelta

        today = date.today()

        entitlement_months = timeline.get("entitlement_months", 0)
        financing_months = timeline.get("financing_months", 0)
        construction_months = timeline.get("construction_months", 0)

        if project.current_stage in [PipelineStage.CONCEPT, PipelineStage.PRE_DEVELOPMENT]:
            project.predicted_entitlement_complete = today + timedelta(
                days=int(entitlement_months * 30 + 180)
            )
        if project.entitlement_complete:
            project.predicted_financing_complete = project.entitlement_complete + timedelta(
                days=int(financing_months * 30)
            )
        elif project.predicted_entitlement_complete:
            project.predicted_financing_complete = project.predicted_entitlement_complete + timedelta(
                days=int(financing_months * 30)
            )

        total_months = timeline.get("total_concept_to_co_months", 0)
        if project.concept_start:
            project.predicted_co = project.concept_start + timedelta(
                days=int(total_months * 30)
            )

        project.prediction_confidence = result.get("confidence_intervals", {}).get(
            "confidence_level", 0.5
        )
        project.prediction_last_updated = datetime.utcnow()
