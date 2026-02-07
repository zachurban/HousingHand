"""Common database query patterns for the HousingHand pipeline."""

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.barrier import ProjectBarrier
from src.models.enums import OverallHealth, PipelineStage
from src.models.funding_source import FundingSource
from src.models.project import Project


def get_project(db: Session, project_id: UUID) -> Project | None:
    """Fetch a single project by ID."""
    return db.get(Project, project_id)


def get_project_by_slug(db: Session, slug: str) -> Project | None:
    """Fetch a single project by its URL-friendly slug."""
    stmt = select(Project).where(Project.project_slug == slug)
    return db.scalars(stmt).first()


def query_projects(
    db: Session,
    *,
    jurisdiction: str | None = None,
    city: str | None = None,
    state: str | None = None,
    current_stage: PipelineStage | None = None,
    stages: list[PipelineStage] | None = None,
    overall_health: OverallHealth | None = None,
    affordable_units_min: int | None = None,
    developer_org: str | None = None,
    date_range_start: date | None = None,
    date_range_end: date | None = None,
    funding_source_organization: str | None = None,
    limit: int = 1000,
    offset: int = 0,
) -> list[Project]:
    """Flexible project query with multiple filter options."""
    stmt = select(Project)

    if jurisdiction:
        stmt = stmt.where(Project.jurisdiction == jurisdiction)
    if city:
        stmt = stmt.where(Project.city == city)
    if state:
        stmt = stmt.where(Project.state == state)
    if current_stage:
        stmt = stmt.where(Project.current_stage == current_stage)
    if stages:
        stmt = stmt.where(Project.current_stage.in_(stages))
    if overall_health:
        stmt = stmt.where(Project.overall_health == overall_health)
    if affordable_units_min is not None:
        stmt = stmt.where(Project.affordable_units >= affordable_units_min)
    if developer_org:
        stmt = stmt.where(Project.developer_org == developer_org)
    if date_range_start:
        stmt = stmt.where(Project.created_at >= date_range_start)
    if date_range_end:
        stmt = stmt.where(Project.created_at <= date_range_end)
    if funding_source_organization:
        stmt = stmt.join(FundingSource).where(
            FundingSource.provider_organization == funding_source_organization
        )

    stmt = stmt.order_by(Project.updated_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def query_similar_projects(
    db: Session,
    *,
    jurisdiction: str | None = None,
    state: str | None = None,
    unit_count_range: tuple[float, float] | None = None,
    building_type: str | None = None,
    completed_only: bool = False,
    limit: int = 50,
) -> list[Project]:
    """Find similar projects for peer benchmarking."""
    stmt = select(Project)

    if jurisdiction:
        stmt = stmt.where(Project.jurisdiction == jurisdiction)
    if state:
        stmt = stmt.where(Project.state == state)
    if unit_count_range:
        low, high = unit_count_range
        stmt = stmt.where(Project.total_units >= low, Project.total_units <= high)
    if building_type:
        stmt = stmt.where(Project.building_type == building_type)
    if completed_only:
        stmt = stmt.where(
            Project.current_stage.in_([PipelineStage.OPERATIONS, PipelineStage.LEASE_UP])
        )

    stmt = stmt.limit(limit)
    return list(db.scalars(stmt).all())


def get_projects_by_entitlement_window(
    db: Session,
    jurisdiction: str,
    entitlement_start_before: date | None = None,
    entitlement_start_after: date | None = None,
    entitlement_complete_before: date | None = None,
) -> list[Project]:
    """Query projects by entitlement date windows (for reform impact analysis)."""
    stmt = select(Project).where(Project.jurisdiction == jurisdiction)

    if entitlement_start_before:
        stmt = stmt.where(Project.entitlement_start <= entitlement_start_before)
    if entitlement_start_after:
        stmt = stmt.where(Project.entitlement_start >= entitlement_start_after)
    if entitlement_complete_before:
        stmt = stmt.where(Project.entitlement_complete <= entitlement_complete_before)

    return list(db.scalars(stmt).all())


def get_abandoned_projects(
    db: Session,
    jurisdiction: str,
    abandoned_before: date | None = None,
    stage_when_abandoned: PipelineStage | None = None,
) -> list[Project]:
    """Query projects that were abandoned."""
    stmt = select(Project).where(
        Project.jurisdiction == jurisdiction,
        Project.current_stage == PipelineStage.ABANDONED,
    )

    if abandoned_before:
        stmt = stmt.where(Project.updated_at <= abandoned_before)

    return list(db.scalars(stmt).all())


def get_jurisdiction_project_count(db: Session, jurisdiction: str) -> int:
    """Count total projects in a jurisdiction."""
    stmt = select(func.count(Project.project_id)).where(
        Project.jurisdiction == jurisdiction
    )
    return db.scalar(stmt) or 0


def get_portfolio_summary_stats(
    db: Session,
    jurisdiction: str | None = None,
    city: str | None = None,
    state: str | None = None,
) -> dict:
    """Get aggregate statistics for portfolio views."""
    stmt = select(
        func.count(Project.project_id).label("total_projects"),
        func.sum(Project.total_units).label("total_units"),
        func.sum(Project.affordable_units).label("total_affordable_units"),
        func.sum(Project.total_development_cost).label("total_cost"),
        func.sum(Project.funding_gap).label("total_funding_gap"),
    )

    if jurisdiction:
        stmt = stmt.where(Project.jurisdiction == jurisdiction)
    if city:
        stmt = stmt.where(Project.city == city)
    if state:
        stmt = stmt.where(Project.state == state)

    result = db.execute(stmt).first()
    if result is None:
        return {
            "total_projects": 0,
            "total_units": 0,
            "total_affordable_units": 0,
            "total_cost": 0,
            "total_funding_gap": 0,
        }

    return {
        "total_projects": result.total_projects or 0,
        "total_units": result.total_units or 0,
        "total_affordable_units": result.total_affordable_units or 0,
        "total_cost": float(result.total_cost or 0),
        "total_funding_gap": float(result.total_funding_gap or 0),
    }


def get_stage_distribution(
    db: Session,
    jurisdiction: str | None = None,
) -> dict[str, int]:
    """Get project counts by pipeline stage."""
    stmt = select(
        Project.current_stage,
        func.count(Project.project_id).label("count"),
    ).group_by(Project.current_stage)

    if jurisdiction:
        stmt = stmt.where(Project.jurisdiction == jurisdiction)

    results = db.execute(stmt).all()
    return {row.current_stage.value: row.count for row in results}


def get_stalled_projects(
    db: Session,
    days_threshold: int = 180,
    jurisdiction: str | None = None,
) -> list[Project]:
    """Find projects stuck in their current stage beyond a threshold."""
    cutoff = date.today() - timedelta(days=days_threshold)
    stmt = select(Project).where(
        Project.stage_entry_date <= cutoff,
        Project.current_stage.notin_([PipelineStage.OPERATIONS, PipelineStage.ABANDONED]),
    )

    if jurisdiction:
        stmt = stmt.where(Project.jurisdiction == jurisdiction)

    stmt = stmt.order_by(Project.stage_entry_date.asc())
    return list(db.scalars(stmt).all())
