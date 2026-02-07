"""Celery tasks for generating stakeholder alerts."""

import logging
from datetime import date, datetime, timedelta

from src.database.connection import get_session_factory
from src.models.enums import OverallHealth, PipelineStage
from src.models.project import Project
from src.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="src.tasks.alert_generation.generate_daily_alerts")
def generate_daily_alerts() -> dict:
    """Generate alerts for projects that need attention."""
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        alerts = []

        # Alert 1: Projects newly at risk
        at_risk = (
            db.query(Project)
            .filter(
                Project.overall_health.in_([OverallHealth.AT_RISK, OverallHealth.STALLED]),
                Project.current_stage.notin_(
                    [PipelineStage.OPERATIONS, PipelineStage.ABANDONED]
                ),
            )
            .all()
        )

        for project in at_risk:
            alerts.append({
                "type": "health_warning",
                "severity": "high" if project.overall_health == OverallHealth.STALLED else "medium",
                "project_id": str(project.project_id),
                "project_name": project.project_name,
                "message": (
                    f"Project '{project.project_name}' is {project.overall_health.value} "
                    f"in {project.current_stage.value} stage "
                    f"({project.days_in_current_stage or 0} days)"
                ),
            })

        # Alert 2: Upcoming milestones (next 14 days)
        upcoming_deadline = date.today() + timedelta(days=14)
        upcoming = (
            db.query(Project)
            .filter(
                Project.next_milestone_date.isnot(None),
                Project.next_milestone_date <= upcoming_deadline,
                Project.next_milestone_date >= date.today(),
            )
            .all()
        )

        for project in upcoming:
            days_until = (project.next_milestone_date - date.today()).days
            alerts.append({
                "type": "milestone_upcoming",
                "severity": "low" if days_until > 7 else "medium",
                "project_id": str(project.project_id),
                "project_name": project.project_name,
                "message": (
                    f"Project '{project.project_name}' has milestone "
                    f"'{project.next_milestone_type}' in {days_until} days"
                ),
            })

        # Alert 3: Large funding gaps
        funding_gap_projects = (
            db.query(Project)
            .filter(
                Project.funding_gap > 0,
                Project.current_stage.in_(
                    [PipelineStage.PRE_DEVELOPMENT, PipelineStage.ENTITLEMENT, PipelineStage.FINANCING]
                ),
            )
            .all()
        )

        for project in funding_gap_projects:
            if project.funding_gap and project.total_development_cost:
                gap_pct = (float(project.funding_gap) / float(project.total_development_cost)) * 100
                if gap_pct > 20:
                    alerts.append({
                        "type": "funding_gap",
                        "severity": "high",
                        "project_id": str(project.project_id),
                        "project_name": project.project_name,
                        "message": (
                            f"Project '{project.project_name}' has a "
                            f"{gap_pct:.0f}% funding gap "
                            f"(${float(project.funding_gap):,.0f})"
                        ),
                    })

        result = {
            "total_alerts": len(alerts),
            "by_severity": {
                "high": len([a for a in alerts if a["severity"] == "high"]),
                "medium": len([a for a in alerts if a["severity"] == "medium"]),
                "low": len([a for a in alerts if a["severity"] == "low"]),
            },
            "alerts": alerts,
            "timestamp": datetime.utcnow().isoformat(),
        }

        logger.info(
            f"Generated {len(alerts)} alerts: "
            f"{result['by_severity']['high']} high, "
            f"{result['by_severity']['medium']} medium, "
            f"{result['by_severity']['low']} low"
        )
        return result

    finally:
        db.close()
