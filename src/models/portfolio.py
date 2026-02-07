"""SQLAlchemy model for portfolio dashboard configurations."""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.connection import Base
from src.models.enums import PortfolioType


class PortfolioDashboard(Base):
    """Saved portfolio configurations for stakeholders."""

    __tablename__ = "portfolio_dashboards"

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    portfolio_name: Mapped[str] = mapped_column(String(300), nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    organization: Mapped[str | None] = mapped_column(String(500))

    portfolio_type: Mapped[PortfolioType] = mapped_column(
        Enum(PortfolioType), nullable=False
    )

    # Filters
    geography_filter: Mapped[dict | None] = mapped_column(JSON)
    funding_filter: Mapped[dict | None] = mapped_column(JSON)
    stage_filter: Mapped[dict | None] = mapped_column(JSON)
    ami_filter: Mapped[dict | None] = mapped_column(JSON)
    date_range_start: Mapped[date | None] = mapped_column(Date)
    date_range_end: Mapped[date | None] = mapped_column(Date)

    # Calculated metrics (cached)
    total_projects: Mapped[int] = mapped_column(Integer, default=0)
    total_units: Mapped[int] = mapped_column(Integer, default=0)
    units_by_stage: Mapped[dict | None] = mapped_column(JSON)
    funding_gap_aggregate: Mapped[float | None] = mapped_column(Numeric(14, 2))
    at_risk_count: Mapped[int] = mapped_column(Integer, default=0)
    velocity_metrics: Mapped[dict | None] = mapped_column(JSON)

    last_calculated: Mapped[datetime | None] = mapped_column(DateTime)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return f"<PortfolioDashboard(name={self.portfolio_name!r}, type={self.portfolio_type})>"
