"""SQLAlchemy model for policy reform tracking."""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, Float, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.connection import Base
from src.models.enums import ConfidenceLevel, ReformType


class PolicyReform(Base):
    """Tracks regulatory changes and measures their impact on development pipelines."""

    __tablename__ = "policy_reforms"

    reform_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    jurisdiction: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    reform_name: Mapped[str] = mapped_column(String(500), nullable=False)
    reform_description: Mapped[str | None] = mapped_column(Text)

    reform_type: Mapped[ReformType] = mapped_column(Enum(ReformType), nullable=False)
    related_friction_topic: Mapped[str | None] = mapped_column(String(300))

    announcement_date: Mapped[date | None] = mapped_column(Date)
    effective_date: Mapped[date | None] = mapped_column(Date)
    implementation_buffer_days: Mapped[int] = mapped_column(Integer, default=30)

    # Impact measurement
    projects_pre_reform: Mapped[int] = mapped_column(Integer, default=0)
    projects_post_reform: Mapped[int] = mapped_column(Integer, default=0)
    pre_reform_median_days: Mapped[int | None] = mapped_column(Integer)
    post_reform_median_days: Mapped[int | None] = mapped_column(Integer)
    days_saved_per_project: Mapped[int | None] = mapped_column(Integer)
    percent_improvement: Mapped[float | None] = mapped_column(Float)

    total_cost_savings: Mapped[float | None] = mapped_column(Numeric(14, 2))
    units_enabled: Mapped[int] = mapped_column(Integer, default=0)
    projects_no_longer_delayed: Mapped[int] = mapped_column(Integer, default=0)

    statistical_significance_p_value: Mapped[float | None] = mapped_column(Float)
    confidence_level: Mapped[ConfidenceLevel | None] = mapped_column(Enum(ConfidenceLevel))

    # Source tracking
    source: Mapped[str | None] = mapped_column(String(300))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    ordinance_number: Mapped[str | None] = mapped_column(String(100))

    impact_last_measured: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return f"<PolicyReform(name={self.reform_name!r}, jurisdiction={self.jurisdiction})>"
