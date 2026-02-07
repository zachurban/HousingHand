"""SQLAlchemy model for project barriers and friction points."""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.models.enums import BarrierStage


class ProjectBarrier(Base):
    """Links projects to specific regulatory friction points."""

    __tablename__ = "project_barriers"

    barrier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        __import__("sqlalchemy").ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    barrier_type: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    barrier_description: Mapped[str | None] = mapped_column(Text)
    jurisdiction: Mapped[str | None] = mapped_column(String(300))

    # From HousingLens
    friction_score: Mapped[int | None] = mapped_column(Integer)
    jurisdiction_rank: Mapped[int | None] = mapped_column(Integer)

    # Project-specific impact
    stage_encountered: Mapped[BarrierStage | None] = mapped_column(Enum(BarrierStage))
    date_encountered: Mapped[date | None] = mapped_column(Date)
    date_resolved: Mapped[date | None] = mapped_column(Date)
    days_delayed: Mapped[int] = mapped_column(Integer, default=0)
    cost_impact: Mapped[float] = mapped_column(Numeric(12, 2), default=0)

    resolution_strategy: Mapped[str | None] = mapped_column(Text)
    variance_required: Mapped[bool] = mapped_column(Boolean, default=False)
    variance_granted: Mapped[bool | None] = mapped_column(Boolean)
    appeal_filed: Mapped[bool] = mapped_column(Boolean, default=False)

    lessons_learned: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationship
    project = relationship("Project", back_populates="barriers")

    def __repr__(self) -> str:
        return f"<ProjectBarrier(type={self.barrier_type!r}, days_delayed={self.days_delayed})>"
