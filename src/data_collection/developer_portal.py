"""Developer portal service for project data submission and updates."""

import logging
import re
import uuid
from datetime import date, datetime

from sqlalchemy.orm import Session

from src.models.enums import DataSource, PipelineStage
from src.models.project import Project

logger = logging.getLogger(__name__)


def _slugify(name: str) -> str:
    """Convert a project name to a URL-friendly slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug[:500]


class DeveloperPortalService:
    """Service layer for developer project submissions."""

    def __init__(self, db: Session):
        self.db = db

    def create_project(self, data: dict) -> Project:
        """Create a new project from developer portal submission."""
        slug = _slugify(data["project_name"])

        # Ensure unique slug
        existing = self.db.query(Project).filter(Project.project_slug == slug).first()
        if existing:
            slug = f"{slug}-{uuid.uuid4().hex[:6]}"

        project = Project(
            project_name=data["project_name"],
            project_slug=slug,
            address=data.get("address"),
            city=data.get("city"),
            county=data.get("county"),
            state=data.get("state"),
            zip=data.get("zip"),
            jurisdiction=data.get("jurisdiction"),
            developer_org=data.get("developer_org"),
            developer_contact=data.get("developer_contact"),
            total_units=data.get("total_units", 0),
            affordable_units=data.get("affordable_units", 0),
            building_type=data.get("building_type"),
            current_stage=data.get("current_stage", PipelineStage.CONCEPT),
            stage_entry_date=date.today(),
            concept_start=date.today(),
            data_source=DataSource.DEVELOPER_PORTAL,
            data_quality_score=0.5,
            data_completeness=self._calculate_completeness(data),
            created_by=data.get("created_by", "developer_portal"),
        )

        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        logger.info(f"Created project: {project.project_slug} ({project.project_id})")
        return project

    def update_project_stage(
        self,
        project_id: uuid.UUID,
        new_stage: PipelineStage,
        completion_date: date | None = None,
    ) -> Project:
        """Update a project's pipeline stage and record transition."""
        project = self.db.get(Project, project_id)
        if project is None:
            raise ValueError(f"Project not found: {project_id}")

        old_stage = project.current_stage
        now = completion_date or date.today()

        # Record completion of current stage
        stage_complete_attr = f"{old_stage.value}_complete"
        if hasattr(project, stage_complete_attr):
            setattr(project, stage_complete_attr, now)

        # Calculate duration of completed stage
        stage_start_attr = f"{old_stage.value}_start"
        start_date = getattr(project, stage_start_attr, None)
        if start_date:
            duration_attr = f"{old_stage.value}_duration_days"
            if hasattr(project, duration_attr):
                setattr(project, duration_attr, (now - start_date).days)

        # Set new stage
        project.current_stage = new_stage
        project.stage_entry_date = now

        # Record start of new stage
        new_stage_start_attr = f"{new_stage.value}_start"
        if hasattr(project, new_stage_start_attr):
            setattr(project, new_stage_start_attr, now)

        # Update elapsed days
        if project.concept_start:
            project.total_elapsed_days = (now - project.concept_start).days

        # Update groundbreaking tracker
        if new_stage == PipelineStage.CONSTRUCTION and project.concept_start:
            project.concept_to_groundbreaking_days = (now - project.concept_start).days

        project.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(project)

        logger.info(
            f"Project {project.project_slug} transitioned "
            f"{old_stage.value} -> {new_stage.value}"
        )
        return project

    def update_project_costs(self, project_id: uuid.UUID, cost_data: dict) -> Project:
        """Update cost information for a project."""
        project = self.db.get(Project, project_id)
        if project is None:
            raise ValueError(f"Project not found: {project_id}")

        cost_fields = [
            "total_development_cost", "land_acquisition_cost", "hard_costs",
            "soft_costs", "financing_costs", "developer_fee", "reserves",
            "architecture_engineering", "legal_fees", "original_budget",
            "current_budget",
        ]

        for field in cost_fields:
            if field in cost_data:
                setattr(project, field, cost_data[field])

        # Recalculate derived fields
        if project.total_development_cost and project.total_units:
            project.cost_per_unit = project.total_development_cost / project.total_units

        if project.original_budget and project.current_budget:
            project.budget_variance_dollars = project.current_budget - project.original_budget
            project.budget_variance_percent = (
                (project.budget_variance_dollars / project.original_budget) * 100
            )

        project.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(project)
        return project

    @staticmethod
    def _calculate_completeness(data: dict) -> float:
        """Calculate a data completeness score (0-1) based on filled fields."""
        important_fields = [
            "project_name", "address", "city", "state", "jurisdiction",
            "developer_org", "total_units", "affordable_units", "building_type",
            "site_acres", "stories",
        ]
        filled = sum(1 for f in important_fields if data.get(f) is not None)
        return round(filled / len(important_fields), 2)
