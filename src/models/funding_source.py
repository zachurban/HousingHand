"""SQLAlchemy model for project funding sources."""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, Float, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.models.enums import FundingSourceStatus, FundingSourceType


class FundingSource(Base):
    """Funding source linked to a project (many-to-one)."""

    __tablename__ = "funding_sources"

    funding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        __import__("sqlalchemy").ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    source_type: Mapped[FundingSourceType] = mapped_column(
        Enum(FundingSourceType), nullable=False
    )
    source_name: Mapped[str] = mapped_column(String(500), nullable=False)
    provider_organization: Mapped[str | None] = mapped_column(String(500))
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    status: Mapped[FundingSourceStatus] = mapped_column(
        Enum(FundingSourceStatus), nullable=False, default=FundingSourceStatus.ANTICIPATED
    )

    application_date: Mapped[date | None] = mapped_column(Date)
    award_date: Mapped[date | None] = mapped_column(Date)
    closing_date: Mapped[date | None] = mapped_column(Date)
    expected_closing_date: Mapped[date | None] = mapped_column(Date)

    # Debt terms
    interest_rate: Mapped[float | None] = mapped_column(Float)
    term_years: Mapped[int | None] = mapped_column(Integer)
    amortization_years: Mapped[int | None] = mapped_column(Integer)

    # Tax credit details
    credit_amount_annual: Mapped[float | None] = mapped_column(Numeric(14, 2))
    equity_raised: Mapped[float | None] = mapped_column(Numeric(14, 2))
    pricing_percent: Mapped[float | None] = mapped_column(Float)

    # Compliance
    compliance_period_years: Mapped[int | None] = mapped_column(Integer)
    affordability_period_years: Mapped[int | None] = mapped_column(Integer)

    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationship
    project = relationship("Project", back_populates="funding_sources")

    def __repr__(self) -> str:
        return f"<FundingSource(name={self.source_name!r}, type={self.source_type}, amount={self.amount})>"
