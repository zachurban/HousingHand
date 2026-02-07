"""SQLAlchemy model for affordable housing development projects."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.models.enums import (
    BuildingType,
    DataSource,
    NeighborOpposition,
    OverallHealth,
    ParkingType,
    PipelineStage,
    StructureType,
)


class Project(Base):
    """Comprehensive affordable housing project tracking model."""

    __tablename__ = "projects"

    # Identity
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_name: Mapped[str] = mapped_column(String(500), nullable=False)
    project_slug: Mapped[str] = mapped_column(String(500), unique=True, nullable=False, index=True)

    # Location
    address: Mapped[str | None] = mapped_column(String(500))
    city: Mapped[str | None] = mapped_column(String(200), index=True)
    county: Mapped[str | None] = mapped_column(String(200))
    state: Mapped[str | None] = mapped_column(String(2), index=True)
    zip: Mapped[str | None] = mapped_column(String(10))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    jurisdiction: Mapped[str | None] = mapped_column(String(300), index=True)
    neighborhood: Mapped[str | None] = mapped_column(String(200))
    census_tract: Mapped[str | None] = mapped_column(String(20))

    # Development Team
    developer_org: Mapped[str | None] = mapped_column(String(500))
    developer_contact: Mapped[str | None] = mapped_column(String(300))
    architect: Mapped[str | None] = mapped_column(String(500))
    general_contractor: Mapped[str | None] = mapped_column(String(500))
    property_manager: Mapped[str | None] = mapped_column(String(500))

    # Project Characteristics
    site_acres: Mapped[float | None] = mapped_column(Float)
    building_type: Mapped[BuildingType | None] = mapped_column(Enum(BuildingType))
    structure_type: Mapped[StructureType | None] = mapped_column(Enum(StructureType))
    stories: Mapped[int | None] = mapped_column(Integer)
    parking_spaces: Mapped[int | None] = mapped_column(Integer)
    parking_type: Mapped[ParkingType | None] = mapped_column(Enum(ParkingType))

    # Unit Mix
    total_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    affordable_units: Mapped[int] = mapped_column(Integer, default=0)
    market_units: Mapped[int] = mapped_column(Integer, default=0)
    studio_units: Mapped[int] = mapped_column(Integer, default=0)
    one_br_units: Mapped[int] = mapped_column(Integer, default=0)
    two_br_units: Mapped[int] = mapped_column(Integer, default=0)
    three_br_units: Mapped[int] = mapped_column(Integer, default=0)
    four_plus_br_units: Mapped[int] = mapped_column(Integer, default=0)

    # AMI Targeting
    ami_30_units: Mapped[int] = mapped_column(Integer, default=0)
    ami_40_units: Mapped[int] = mapped_column(Integer, default=0)
    ami_50_units: Mapped[int] = mapped_column(Integer, default=0)
    ami_60_units: Mapped[int] = mapped_column(Integer, default=0)
    ami_80_units: Mapped[int] = mapped_column(Integer, default=0)
    market_rate_units: Mapped[int] = mapped_column(Integer, default=0)

    # Special Populations
    senior_units: Mapped[int] = mapped_column(Integer, default=0)
    family_units: Mapped[int] = mapped_column(Integer, default=0)
    psf_units: Mapped[int] = mapped_column(Integer, default=0)
    veteran_units: Mapped[int] = mapped_column(Integer, default=0)
    homeless_set_aside: Mapped[int] = mapped_column(Integer, default=0)

    # Pipeline Status
    current_stage: Mapped[PipelineStage] = mapped_column(
        Enum(PipelineStage), nullable=False, default=PipelineStage.CONCEPT, index=True
    )
    stage_entry_date: Mapped[date | None] = mapped_column(Date)
    days_in_current_stage: Mapped[int | None] = mapped_column(Integer)
    overall_health: Mapped[OverallHealth | None] = mapped_column(Enum(OverallHealth))
    health_score: Mapped[float | None] = mapped_column(Float)
    last_milestone_date: Mapped[date | None] = mapped_column(Date)
    next_milestone_date: Mapped[date | None] = mapped_column(Date)
    next_milestone_type: Mapped[str | None] = mapped_column(String(200))

    # Timeline - Actual
    concept_start: Mapped[date | None] = mapped_column(Date)
    concept_complete: Mapped[date | None] = mapped_column(Date)
    concept_duration_days: Mapped[int | None] = mapped_column(Integer)

    pre_development_start: Mapped[date | None] = mapped_column(Date)
    pre_development_complete: Mapped[date | None] = mapped_column(Date)
    pre_development_duration_days: Mapped[int | None] = mapped_column(Integer)

    entitlement_start: Mapped[date | None] = mapped_column(Date)
    entitlement_complete: Mapped[date | None] = mapped_column(Date)
    entitlement_duration_days: Mapped[int | None] = mapped_column(Integer)

    financing_start: Mapped[date | None] = mapped_column(Date)
    financing_complete: Mapped[date | None] = mapped_column(Date)
    financing_duration_days: Mapped[int | None] = mapped_column(Integer)

    construction_start: Mapped[date | None] = mapped_column(Date)
    construction_complete: Mapped[date | None] = mapped_column(Date)
    construction_duration_days: Mapped[int | None] = mapped_column(Integer)

    lease_up_start: Mapped[date | None] = mapped_column(Date)
    lease_up_complete: Mapped[date | None] = mapped_column(Date)
    lease_up_duration_days: Mapped[int | None] = mapped_column(Integer)

    total_elapsed_days: Mapped[int | None] = mapped_column(Integer)
    concept_to_groundbreaking_days: Mapped[int | None] = mapped_column(Integer)
    concept_to_co_days: Mapped[int | None] = mapped_column(Integer)

    # Timeline - Predicted
    predicted_entitlement_complete: Mapped[date | None] = mapped_column(Date)
    predicted_financing_complete: Mapped[date | None] = mapped_column(Date)
    predicted_groundbreaking: Mapped[date | None] = mapped_column(Date)
    predicted_co: Mapped[date | None] = mapped_column(Date)
    prediction_confidence: Mapped[float | None] = mapped_column(Float)
    prediction_last_updated: Mapped[datetime | None] = mapped_column(DateTime)

    # Costs
    total_development_cost: Mapped[float | None] = mapped_column(Numeric(14, 2))
    cost_per_unit: Mapped[float | None] = mapped_column(Numeric(12, 2))
    cost_per_square_foot: Mapped[float | None] = mapped_column(Numeric(10, 2))

    land_acquisition_cost: Mapped[float | None] = mapped_column(Numeric(14, 2))
    hard_costs: Mapped[float | None] = mapped_column(Numeric(14, 2))
    soft_costs: Mapped[float | None] = mapped_column(Numeric(14, 2))
    financing_costs: Mapped[float | None] = mapped_column(Numeric(14, 2))
    developer_fee: Mapped[float | None] = mapped_column(Numeric(14, 2))
    reserves: Mapped[float | None] = mapped_column(Numeric(14, 2))

    # Cost Breakdown Detail
    architecture_engineering: Mapped[float | None] = mapped_column(Numeric(12, 2))
    legal_fees: Mapped[float | None] = mapped_column(Numeric(12, 2))
    environmental_review: Mapped[float | None] = mapped_column(Numeric(12, 2))
    market_study: Mapped[float | None] = mapped_column(Numeric(12, 2))
    appraisal: Mapped[float | None] = mapped_column(Numeric(12, 2))
    title_insurance: Mapped[float | None] = mapped_column(Numeric(12, 2))
    construction_loan_interest: Mapped[float | None] = mapped_column(Numeric(12, 2))
    permanent_loan_fees: Mapped[float | None] = mapped_column(Numeric(12, 2))

    # Friction-Induced Costs
    friction_induced_costs: Mapped[float | None] = mapped_column(Numeric(14, 2))
    regulatory_delay_costs: Mapped[float | None] = mapped_column(Numeric(14, 2))
    redesign_costs: Mapped[float | None] = mapped_column(Numeric(12, 2))
    carrying_costs_from_delays: Mapped[float | None] = mapped_column(Numeric(14, 2))

    # Cost Variance
    original_budget: Mapped[float | None] = mapped_column(Numeric(14, 2))
    current_budget: Mapped[float | None] = mapped_column(Numeric(14, 2))
    budget_variance_dollars: Mapped[float | None] = mapped_column(Numeric(14, 2))
    budget_variance_percent: Mapped[float | None] = mapped_column(Float)
    budget_variance_reasons: Mapped[dict | None] = mapped_column(JSON)

    # Funding Stack
    funding_stack: Mapped[dict | None] = mapped_column(JSON)
    total_funding_committed: Mapped[float | None] = mapped_column(Numeric(14, 2))
    funding_gap: Mapped[float | None] = mapped_column(Numeric(14, 2))
    debt_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    equity_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    subsidy_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))

    # Regulatory Friction Analysis
    jurisdiction_friction_score: Mapped[int | None] = mapped_column(Integer)
    predicted_delay_from_friction: Mapped[int | None] = mapped_column(Integer)
    actual_delay_sofar: Mapped[int | None] = mapped_column(Integer)
    primary_friction_points: Mapped[dict | None] = mapped_column(JSON)

    # Stakeholder Interactions
    housing_mind_queries: Mapped[int] = mapped_column(Integer, default=0)
    top_query_categories: Mapped[dict | None] = mapped_column(JSON)
    public_meetings_attended: Mapped[int] = mapped_column(Integer, default=0)
    variance_hearings: Mapped[int] = mapped_column(Integer, default=0)
    design_review_iterations: Mapped[int] = mapped_column(Integer, default=0)
    neighbor_opposition_level: Mapped[NeighborOpposition | None] = mapped_column(
        Enum(NeighborOpposition)
    )
    appeals_filed: Mapped[int] = mapped_column(Integer, default=0)

    # Risk Factors
    risk_factors: Mapped[dict | None] = mapped_column(JSON)
    risk_score: Mapped[float | None] = mapped_column(Float)
    pending_approvals: Mapped[dict | None] = mapped_column(JSON)
    active_oppositions: Mapped[dict | None] = mapped_column(JSON)

    # Data Quality & Provenance
    data_source: Mapped[DataSource | None] = mapped_column(Enum(DataSource))
    data_quality_score: Mapped[float | None] = mapped_column(Float)
    last_verified: Mapped[date | None] = mapped_column(Date)
    verified_by: Mapped[str | None] = mapped_column(String(200))
    data_completeness: Mapped[float | None] = mapped_column(Float)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by: Mapped[str | None] = mapped_column(String(200))
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    # Relationships
    funding_sources = relationship("FundingSource", back_populates="project", cascade="all, delete-orphan")
    barriers = relationship("ProjectBarrier", back_populates="project", cascade="all, delete-orphan")

    def get_stage_duration(self, stage: str) -> int | None:
        """Return duration in days for a given pipeline stage."""
        attr = f"{stage}_duration_days"
        return getattr(self, attr, None)

    def __repr__(self) -> str:
        return f"<Project(name={self.project_name!r}, stage={self.current_stage})>"
