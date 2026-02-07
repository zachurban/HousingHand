"""Full CRUD endpoints for affordable housing development projects."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.dependencies import DbSession, PaginationDep
from src.models.enums import (
    BuildingType,
    DataSource,
    NeighborOpposition,
    OverallHealth,
    PipelineStage,
    StructureType,
)
from src.models.project import Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class LocationSchema(BaseModel):
    """Location fields shared by create / update / response schemas."""

    address: str | None = None
    city: str | None = None
    county: str | None = None
    state: str | None = Field(None, max_length=2)
    zip: str | None = Field(None, max_length=10)
    latitude: float | None = None
    longitude: float | None = None
    jurisdiction: str | None = None
    neighborhood: str | None = None
    census_tract: str | None = None

    model_config = {"from_attributes": True}


class DevelopmentTeamSchema(BaseModel):
    """Development team contacts."""

    developer_org: str | None = None
    developer_contact: str | None = None
    architect: str | None = None
    general_contractor: str | None = None
    property_manager: str | None = None

    model_config = {"from_attributes": True}


class UnitMixSchema(BaseModel):
    """Unit count breakdown."""

    total_units: int = Field(0, ge=0)
    affordable_units: int = Field(0, ge=0)
    market_units: int = Field(0, ge=0)
    studio_units: int = Field(0, ge=0)
    one_br_units: int = Field(0, ge=0)
    two_br_units: int = Field(0, ge=0)
    three_br_units: int = Field(0, ge=0)
    four_plus_br_units: int = Field(0, ge=0)

    model_config = {"from_attributes": True}


class AMITargetingSchema(BaseModel):
    """Area Median Income unit targeting."""

    ami_30_units: int = Field(0, ge=0)
    ami_40_units: int = Field(0, ge=0)
    ami_50_units: int = Field(0, ge=0)
    ami_60_units: int = Field(0, ge=0)
    ami_80_units: int = Field(0, ge=0)
    market_rate_units: int = Field(0, ge=0)

    model_config = {"from_attributes": True}


class SpecialPopulationsSchema(BaseModel):
    """Special population unit allocations."""

    senior_units: int = Field(0, ge=0)
    family_units: int = Field(0, ge=0)
    psf_units: int = Field(0, ge=0)
    veteran_units: int = Field(0, ge=0)
    homeless_set_aside: int = Field(0, ge=0)

    model_config = {"from_attributes": True}


class CostSchema(BaseModel):
    """Project cost information."""

    total_development_cost: float | None = None
    cost_per_unit: float | None = None
    cost_per_square_foot: float | None = None
    land_acquisition_cost: float | None = None
    hard_costs: float | None = None
    soft_costs: float | None = None
    financing_costs: float | None = None
    developer_fee: float | None = None
    reserves: float | None = None

    model_config = {"from_attributes": True}


class FundingStackSchema(BaseModel):
    """Aggregate funding stack information."""

    funding_stack: dict[str, Any] | None = None
    total_funding_committed: float | None = None
    funding_gap: float | None = None
    debt_amount: float | None = None
    equity_amount: float | None = None
    subsidy_amount: float | None = None

    model_config = {"from_attributes": True}


class TimelineSchema(BaseModel):
    """Actual timeline milestones."""

    concept_start: date | None = None
    concept_complete: date | None = None
    pre_development_start: date | None = None
    pre_development_complete: date | None = None
    entitlement_start: date | None = None
    entitlement_complete: date | None = None
    financing_start: date | None = None
    financing_complete: date | None = None
    construction_start: date | None = None
    construction_complete: date | None = None
    lease_up_start: date | None = None
    lease_up_complete: date | None = None

    model_config = {"from_attributes": True}


# -- Request schemas --------------------------------------------------------

class ProjectCreate(BaseModel):
    """Schema for creating a new project.

    Only ``project_name`` and ``total_units`` are truly required -- every
    other field is optional so that early-stage projects can be entered with
    minimal data.
    """

    project_name: str = Field(..., min_length=1, max_length=500)
    project_slug: str | None = Field(
        None,
        max_length=500,
        description="URL-friendly slug.  Auto-generated from project_name if omitted.",
    )

    # Location
    address: str | None = None
    city: str | None = None
    county: str | None = None
    state: str | None = Field(None, max_length=2)
    zip: str | None = Field(None, max_length=10)
    latitude: float | None = None
    longitude: float | None = None
    jurisdiction: str | None = None
    neighborhood: str | None = None
    census_tract: str | None = None

    # Development team
    developer_org: str | None = None
    developer_contact: str | None = None
    architect: str | None = None
    general_contractor: str | None = None
    property_manager: str | None = None

    # Characteristics
    site_acres: float | None = None
    building_type: BuildingType | None = None
    structure_type: StructureType | None = None
    stories: int | None = Field(None, ge=1)
    parking_spaces: int | None = Field(None, ge=0)

    # Units
    total_units: int = Field(0, ge=0)
    affordable_units: int = Field(0, ge=0)
    market_units: int = Field(0, ge=0)
    studio_units: int = Field(0, ge=0)
    one_br_units: int = Field(0, ge=0)
    two_br_units: int = Field(0, ge=0)
    three_br_units: int = Field(0, ge=0)
    four_plus_br_units: int = Field(0, ge=0)

    # AMI
    ami_30_units: int = Field(0, ge=0)
    ami_40_units: int = Field(0, ge=0)
    ami_50_units: int = Field(0, ge=0)
    ami_60_units: int = Field(0, ge=0)
    ami_80_units: int = Field(0, ge=0)
    market_rate_units: int = Field(0, ge=0)

    # Special populations
    senior_units: int = Field(0, ge=0)
    family_units: int = Field(0, ge=0)
    psf_units: int = Field(0, ge=0)
    veteran_units: int = Field(0, ge=0)
    homeless_set_aside: int = Field(0, ge=0)

    # Pipeline
    current_stage: PipelineStage = PipelineStage.CONCEPT

    # Costs
    total_development_cost: float | None = None
    cost_per_unit: float | None = None
    land_acquisition_cost: float | None = None
    hard_costs: float | None = None
    soft_costs: float | None = None

    # Timeline
    concept_start: date | None = None
    concept_complete: date | None = None
    pre_development_start: date | None = None
    pre_development_complete: date | None = None
    entitlement_start: date | None = None
    entitlement_complete: date | None = None
    financing_start: date | None = None
    financing_complete: date | None = None
    construction_start: date | None = None
    construction_complete: date | None = None

    # Metadata
    data_source: DataSource | None = None
    is_public: bool = False
    notes: str | None = None
    created_by: str | None = None

    model_config = {"json_schema_extra": {
        "examples": [
            {
                "project_name": "Sunrise Village Apartments",
                "city": "Oakland",
                "state": "CA",
                "jurisdiction": "City of Oakland",
                "total_units": 120,
                "affordable_units": 108,
                "building_type": "new_construction",
                "current_stage": "pre_development",
            }
        ]
    }}

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str | None) -> str | None:
        if v is not None:
            return v.upper()
        return v


class ProjectUpdate(BaseModel):
    """Schema for partial project updates (PATCH semantics).

    All fields are optional.  Only provided fields overwrite existing values.
    """

    project_name: str | None = Field(None, min_length=1, max_length=500)
    project_slug: str | None = Field(None, max_length=500)

    # Location
    address: str | None = None
    city: str | None = None
    county: str | None = None
    state: str | None = Field(None, max_length=2)
    zip: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    jurisdiction: str | None = None
    neighborhood: str | None = None
    census_tract: str | None = None

    # Development team
    developer_org: str | None = None
    developer_contact: str | None = None
    architect: str | None = None
    general_contractor: str | None = None
    property_manager: str | None = None

    # Characteristics
    site_acres: float | None = None
    building_type: BuildingType | None = None
    structure_type: StructureType | None = None
    stories: int | None = Field(None, ge=1)
    parking_spaces: int | None = Field(None, ge=0)

    # Units
    total_units: int | None = Field(None, ge=0)
    affordable_units: int | None = Field(None, ge=0)
    market_units: int | None = Field(None, ge=0)
    studio_units: int | None = Field(None, ge=0)
    one_br_units: int | None = Field(None, ge=0)
    two_br_units: int | None = Field(None, ge=0)
    three_br_units: int | None = Field(None, ge=0)
    four_plus_br_units: int | None = Field(None, ge=0)

    # AMI
    ami_30_units: int | None = Field(None, ge=0)
    ami_40_units: int | None = Field(None, ge=0)
    ami_50_units: int | None = Field(None, ge=0)
    ami_60_units: int | None = Field(None, ge=0)
    ami_80_units: int | None = Field(None, ge=0)
    market_rate_units: int | None = Field(None, ge=0)

    # Special populations
    senior_units: int | None = Field(None, ge=0)
    family_units: int | None = Field(None, ge=0)
    psf_units: int | None = Field(None, ge=0)
    veteran_units: int | None = Field(None, ge=0)
    homeless_set_aside: int | None = Field(None, ge=0)

    # Pipeline
    current_stage: PipelineStage | None = None
    overall_health: OverallHealth | None = None
    health_score: float | None = None
    stage_entry_date: date | None = None

    # Costs
    total_development_cost: float | None = None
    cost_per_unit: float | None = None
    land_acquisition_cost: float | None = None
    hard_costs: float | None = None
    soft_costs: float | None = None

    # Timeline
    concept_start: date | None = None
    concept_complete: date | None = None
    pre_development_start: date | None = None
    pre_development_complete: date | None = None
    entitlement_start: date | None = None
    entitlement_complete: date | None = None
    financing_start: date | None = None
    financing_complete: date | None = None
    construction_start: date | None = None
    construction_complete: date | None = None
    lease_up_start: date | None = None
    lease_up_complete: date | None = None

    # Funding stack
    funding_gap: float | None = None
    total_funding_committed: float | None = None

    # Metadata
    data_source: DataSource | None = None
    is_public: bool | None = None
    notes: str | None = None

    model_config = {"json_schema_extra": {
        "examples": [
            {
                "current_stage": "financing",
                "total_development_cost": 42_500_000.00,
                "entitlement_complete": "2025-06-15",
            }
        ]
    }}

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str | None) -> str | None:
        if v is not None:
            return v.upper()
        return v


# -- Response schemas -------------------------------------------------------

class ProjectSummaryResponse(BaseModel):
    """Lightweight project representation for list endpoints."""

    project_id: uuid.UUID
    project_name: str
    project_slug: str
    city: str | None = None
    state: str | None = None
    jurisdiction: str | None = None
    total_units: int
    affordable_units: int
    current_stage: PipelineStage
    overall_health: OverallHealth | None = None
    health_score: float | None = None
    developer_org: str | None = None
    total_development_cost: float | None = None
    funding_gap: float | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectDetailResponse(BaseModel):
    """Full project detail response with all fields."""

    project_id: uuid.UUID
    project_name: str
    project_slug: str

    # Location
    address: str | None = None
    city: str | None = None
    county: str | None = None
    state: str | None = None
    zip: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    jurisdiction: str | None = None
    neighborhood: str | None = None
    census_tract: str | None = None

    # Development team
    developer_org: str | None = None
    developer_contact: str | None = None
    architect: str | None = None
    general_contractor: str | None = None
    property_manager: str | None = None

    # Characteristics
    site_acres: float | None = None
    building_type: BuildingType | None = None
    structure_type: StructureType | None = None
    stories: int | None = None
    parking_spaces: int | None = None

    # Unit mix
    total_units: int
    affordable_units: int
    market_units: int
    studio_units: int
    one_br_units: int
    two_br_units: int
    three_br_units: int
    four_plus_br_units: int

    # AMI targeting
    ami_30_units: int
    ami_40_units: int
    ami_50_units: int
    ami_60_units: int
    ami_80_units: int
    market_rate_units: int

    # Special populations
    senior_units: int
    family_units: int
    psf_units: int
    veteran_units: int
    homeless_set_aside: int

    # Pipeline
    current_stage: PipelineStage
    stage_entry_date: date | None = None
    days_in_current_stage: int | None = None
    overall_health: OverallHealth | None = None
    health_score: float | None = None
    last_milestone_date: date | None = None
    next_milestone_date: date | None = None
    next_milestone_type: str | None = None

    # Timeline - actual
    concept_start: date | None = None
    concept_complete: date | None = None
    concept_duration_days: int | None = None
    pre_development_start: date | None = None
    pre_development_complete: date | None = None
    pre_development_duration_days: int | None = None
    entitlement_start: date | None = None
    entitlement_complete: date | None = None
    entitlement_duration_days: int | None = None
    financing_start: date | None = None
    financing_complete: date | None = None
    financing_duration_days: int | None = None
    construction_start: date | None = None
    construction_complete: date | None = None
    construction_duration_days: int | None = None
    lease_up_start: date | None = None
    lease_up_complete: date | None = None
    lease_up_duration_days: int | None = None
    total_elapsed_days: int | None = None

    # Timeline - predicted
    predicted_entitlement_complete: date | None = None
    predicted_financing_complete: date | None = None
    predicted_groundbreaking: date | None = None
    predicted_co: date | None = None
    prediction_confidence: float | None = None
    prediction_last_updated: datetime | None = None

    # Costs
    total_development_cost: float | None = None
    cost_per_unit: float | None = None
    cost_per_square_foot: float | None = None
    land_acquisition_cost: float | None = None
    hard_costs: float | None = None
    soft_costs: float | None = None
    financing_costs: float | None = None
    developer_fee: float | None = None
    reserves: float | None = None

    # Friction
    friction_induced_costs: float | None = None
    regulatory_delay_costs: float | None = None
    jurisdiction_friction_score: int | None = None
    primary_friction_points: dict[str, Any] | None = None

    # Funding
    funding_stack: dict[str, Any] | None = None
    total_funding_committed: float | None = None
    funding_gap: float | None = None
    debt_amount: float | None = None
    equity_amount: float | None = None
    subsidy_amount: float | None = None

    # Risk
    risk_factors: dict[str, Any] | None = None
    risk_score: float | None = None

    # Stakeholder
    housing_mind_queries: int
    neighbor_opposition_level: NeighborOpposition | None = None
    public_meetings_attended: int
    variance_hearings: int

    # Data quality
    data_source: DataSource | None = None
    data_quality_score: float | None = None
    data_completeness: float | None = None

    # Metadata
    is_public: bool
    notes: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    """Paginated list of projects."""

    items: list[ProjectSummaryResponse]
    total: int = Field(..., description="Total number of projects matching the filters")
    limit: int
    offset: int

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_slug(name: str) -> str:
    """Produce a URL-friendly slug from a project name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    # Append a short uuid fragment to avoid collisions.
    slug = f"{slug}-{uuid.uuid4().hex[:8]}"
    return slug


def _get_project_or_404(db: Session, project_id: uuid.UUID) -> Project:
    """Fetch project by primary key or raise 404."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )
    return project


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List projects",
)
def list_projects(
    db: DbSession,
    pagination: PaginationDep,
    city: str | None = Query(None, description="Filter by city name"),
    state: str | None = Query(None, max_length=2, description="Filter by 2-letter state code"),
    jurisdiction: str | None = Query(None, description="Filter by jurisdiction"),
    current_stage: PipelineStage | None = Query(None, description="Filter by pipeline stage"),
    overall_health: OverallHealth | None = Query(None, description="Filter by overall health"),
    developer_org: str | None = Query(None, description="Filter by developer organization"),
    min_units: int | None = Query(None, ge=0, description="Minimum total units"),
    is_public: bool | None = Query(None, description="Filter by public visibility"),
    search: str | None = Query(None, min_length=1, description="Search project name (ilike)"),
) -> ProjectListResponse:
    """Return a paginated list of projects with optional filters.

    Results are ordered by most recently updated first.  Use the ``search``
    parameter for case-insensitive partial matching on project name.
    """
    stmt = select(Project)

    if city is not None:
        stmt = stmt.where(Project.city == city)
    if state is not None:
        stmt = stmt.where(Project.state == state.upper())
    if jurisdiction is not None:
        stmt = stmt.where(Project.jurisdiction == jurisdiction)
    if current_stage is not None:
        stmt = stmt.where(Project.current_stage == current_stage)
    if overall_health is not None:
        stmt = stmt.where(Project.overall_health == overall_health)
    if developer_org is not None:
        stmt = stmt.where(Project.developer_org == developer_org)
    if min_units is not None:
        stmt = stmt.where(Project.total_units >= min_units)
    if is_public is not None:
        stmt = stmt.where(Project.is_public == is_public)
    if search is not None:
        stmt = stmt.where(Project.project_name.ilike(f"%{search}%"))

    # Total count (before pagination).
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0

    # Paginate.
    stmt = stmt.order_by(Project.updated_at.desc())
    stmt = stmt.limit(pagination.limit).offset(pagination.offset)
    projects = list(db.scalars(stmt).all())

    return ProjectListResponse(
        items=[ProjectSummaryResponse.model_validate(p) for p in projects],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    summary="Get project details",
)
def get_project(
    project_id: uuid.UUID,
    db: DbSession,
) -> ProjectDetailResponse:
    """Return full details for a single project by its UUID."""
    project = _get_project_or_404(db, project_id)
    return ProjectDetailResponse.model_validate(project)


@router.post(
    "",
    response_model=ProjectDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project",
)
def create_project(
    payload: ProjectCreate,
    db: DbSession,
) -> ProjectDetailResponse:
    """Create a new affordable housing development project.

    If ``project_slug`` is not provided it will be auto-generated from the
    project name.
    """
    data = payload.model_dump(exclude_unset=True)

    # Auto-generate slug when not provided.
    if "project_slug" not in data or data["project_slug"] is None:
        data["project_slug"] = _generate_slug(payload.project_name)

    # Guard against duplicate slug.
    existing = db.scalars(
        select(Project).where(Project.project_slug == data["project_slug"])
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A project with slug '{data['project_slug']}' already exists",
        )

    project = Project(**data)
    db.add(project)

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to create project")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create project",
        )

    db.refresh(project)
    return ProjectDetailResponse.model_validate(project)


@router.patch(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    summary="Update an existing project",
)
def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    db: DbSession,
) -> ProjectDetailResponse:
    """Partially update a project.

    Only fields included in the request body are modified; all other fields
    retain their current values (PATCH semantics).
    """
    project = _get_project_or_404(db, project_id)

    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields provided for update",
        )

    # If the slug is being changed, check for conflicts.
    new_slug = update_data.get("project_slug")
    if new_slug is not None and new_slug != project.project_slug:
        conflict = db.scalars(
            select(Project).where(
                Project.project_slug == new_slug,
                Project.project_id != project_id,
            )
        ).first()
        if conflict is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A project with slug '{new_slug}' already exists",
            )

    for field, value in update_data.items():
        setattr(project, field, value)

    project.updated_at = datetime.utcnow()

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to update project %s", project_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update project",
        )

    db.refresh(project)
    return ProjectDetailResponse.model_validate(project)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project",
)
def delete_project(
    project_id: uuid.UUID,
    db: DbSession,
) -> None:
    """Permanently delete a project and its associated data.

    This cascades to related funding sources and project barriers.
    """
    project = _get_project_or_404(db, project_id)

    try:
        db.delete(project)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to delete project %s", project_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete project",
        )

    logger.info("Deleted project %s (%s)", project_id, project.project_name)
