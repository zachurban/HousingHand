"""SQLAlchemy model for peer benchmarking groups."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.connection import Base
from src.models.enums import AMIMixCategory, BuildingType


class PeerGroup(Base):
    """Defines comparable project cohorts for benchmarking."""

    __tablename__ = "peer_groups"

    peer_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    group_name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Similarity criteria
    jurisdiction: Mapped[str | None] = mapped_column(String(300), index=True)
    unit_count_min: Mapped[int | None] = mapped_column(Integer)
    unit_count_max: Mapped[int | None] = mapped_column(Integer)
    ami_mix_category: Mapped[AMIMixCategory | None] = mapped_column(Enum(AMIMixCategory))
    building_type: Mapped[BuildingType | None] = mapped_column(Enum(BuildingType))

    # Benchmark statistics (calculated)
    project_count: Mapped[int] = mapped_column(Integer, default=0)
    median_concept_duration: Mapped[int | None] = mapped_column(Integer)
    median_pre_dev_duration: Mapped[int | None] = mapped_column(Integer)
    median_entitlement_duration: Mapped[int | None] = mapped_column(Integer)
    median_financing_duration: Mapped[int | None] = mapped_column(Integer)
    median_construction_duration: Mapped[int | None] = mapped_column(Integer)
    median_total_duration: Mapped[int | None] = mapped_column(Integer)

    median_cost_per_unit: Mapped[float | None] = mapped_column(Numeric(12, 2))
    p25_cost_per_unit: Mapped[float | None] = mapped_column(Numeric(12, 2))
    p75_cost_per_unit: Mapped[float | None] = mapped_column(Numeric(12, 2))

    last_calculated: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return f"<PeerGroup(name={self.group_name!r}, projects={self.project_count})>"
