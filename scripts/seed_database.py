#!/usr/bin/env python3
"""Seed the database with sample project data for development and testing."""

import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database.connection import Base, get_engine, get_session_factory
from src.models.barrier import ProjectBarrier
from src.models.enums import (
    BarrierStage,
    BuildingType,
    DataSource,
    FundingSourceStatus,
    FundingSourceType,
    NeighborOpposition,
    OverallHealth,
    PipelineStage,
    StructureType,
)
from src.models.funding_source import FundingSource
from src.models.project import Project

SAMPLE_PROJECTS = [
    {
        "project_name": "Sunrise Terrace Apartments",
        "project_slug": "sunrise-terrace-apartments",
        "address": "1200 Main Street",
        "city": "Sacramento",
        "county": "Sacramento",
        "state": "CA",
        "zip": "95814",
        "jurisdiction": "Sacramento, CA",
        "developer_org": "Community Housing Partners",
        "total_units": 80,
        "affordable_units": 72,
        "market_units": 8,
        "ami_30_units": 20,
        "ami_50_units": 32,
        "ami_60_units": 20,
        "building_type": BuildingType.NEW_CONSTRUCTION,
        "structure_type": StructureType.WOOD_FRAME,
        "stories": 4,
        "parking_spaces": 60,
        "current_stage": PipelineStage.CONSTRUCTION,
        "overall_health": OverallHealth.ON_TRACK,
        "health_score": 82.5,
        "concept_start": date.today() - timedelta(days=720),
        "entitlement_start": date.today() - timedelta(days=540),
        "entitlement_complete": date.today() - timedelta(days=300),
        "entitlement_duration_days": 240,
        "financing_start": date.today() - timedelta(days=300),
        "financing_complete": date.today() - timedelta(days=180),
        "financing_duration_days": 120,
        "construction_start": date.today() - timedelta(days=180),
        "total_development_cost": 32_000_000,
        "cost_per_unit": 400_000,
        "hard_costs": 22_000_000,
        "soft_costs": 5_500_000,
        "land_acquisition_cost": 3_000_000,
        "data_source": DataSource.DEVELOPER_PORTAL,
        "data_quality_score": 0.85,
    },
    {
        "project_name": "Oak Park Senior Village",
        "project_slug": "oak-park-senior-village",
        "address": "450 Broadway",
        "city": "Oakland",
        "county": "Alameda",
        "state": "CA",
        "zip": "94607",
        "jurisdiction": "Oakland, CA",
        "developer_org": "Affordable Seniors Inc",
        "total_units": 120,
        "affordable_units": 120,
        "senior_units": 120,
        "ami_30_units": 30,
        "ami_50_units": 50,
        "ami_60_units": 40,
        "building_type": BuildingType.NEW_CONSTRUCTION,
        "structure_type": StructureType.CONCRETE,
        "stories": 6,
        "current_stage": PipelineStage.ENTITLEMENT,
        "overall_health": OverallHealth.AT_RISK,
        "health_score": 55.0,
        "concept_start": date.today() - timedelta(days=400),
        "entitlement_start": date.today() - timedelta(days=250),
        "total_development_cost": 55_000_000,
        "cost_per_unit": 458_333,
        "jurisdiction_friction_score": 720,
        "neighbor_opposition_level": NeighborOpposition.MODERATE,
        "data_source": DataSource.PUBLIC_RECORDS,
        "data_quality_score": 0.7,
    },
    {
        "project_name": "Riverdale Family Homes",
        "project_slug": "riverdale-family-homes",
        "address": "789 Elm Street",
        "city": "Portland",
        "county": "Multnomah",
        "state": "OR",
        "zip": "97201",
        "jurisdiction": "Portland, OR",
        "developer_org": "Northwest Housing Alliance",
        "total_units": 45,
        "affordable_units": 45,
        "family_units": 45,
        "ami_30_units": 10,
        "ami_50_units": 20,
        "ami_60_units": 15,
        "building_type": BuildingType.NEW_CONSTRUCTION,
        "structure_type": StructureType.WOOD_FRAME,
        "stories": 3,
        "current_stage": PipelineStage.FINANCING,
        "overall_health": OverallHealth.ON_TRACK,
        "health_score": 75.0,
        "concept_start": date.today() - timedelta(days=500),
        "entitlement_complete": date.today() - timedelta(days=90),
        "financing_start": date.today() - timedelta(days=90),
        "total_development_cost": 18_000_000,
        "cost_per_unit": 400_000,
        "funding_gap": 2_500_000,
        "data_source": DataSource.DEVELOPER_PORTAL,
        "data_quality_score": 0.8,
    },
    {
        "project_name": "Metro Heights Mixed-Use",
        "project_slug": "metro-heights-mixed-use",
        "address": "200 Central Avenue",
        "city": "Denver",
        "county": "Denver",
        "state": "CO",
        "zip": "80202",
        "jurisdiction": "Denver, CO",
        "developer_org": "Mountain West Development",
        "total_units": 200,
        "affordable_units": 100,
        "market_units": 100,
        "ami_50_units": 40,
        "ami_60_units": 40,
        "ami_80_units": 20,
        "building_type": BuildingType.NEW_CONSTRUCTION,
        "structure_type": StructureType.STEEL,
        "stories": 12,
        "current_stage": PipelineStage.PRE_DEVELOPMENT,
        "overall_health": OverallHealth.ON_TRACK,
        "health_score": 90.0,
        "concept_start": date.today() - timedelta(days=120),
        "pre_development_start": date.today() - timedelta(days=60),
        "total_development_cost": 85_000_000,
        "cost_per_unit": 425_000,
        "data_source": DataSource.DEVELOPER_PORTAL,
        "data_quality_score": 0.6,
    },
    {
        "project_name": "Heritage Court Rehabilitation",
        "project_slug": "heritage-court-rehab",
        "address": "55 Heritage Lane",
        "city": "Austin",
        "county": "Travis",
        "state": "TX",
        "zip": "78701",
        "jurisdiction": "Austin, TX",
        "developer_org": "Lone Star Affordable Housing",
        "total_units": 60,
        "affordable_units": 60,
        "ami_30_units": 15,
        "ami_50_units": 25,
        "ami_60_units": 20,
        "building_type": BuildingType.SUBSTANTIAL_REHAB,
        "structure_type": StructureType.WOOD_FRAME,
        "stories": 2,
        "current_stage": PipelineStage.STALLED,
        "overall_health": OverallHealth.STALLED,
        "health_score": 25.0,
        "concept_start": date.today() - timedelta(days=900),
        "entitlement_start": date.today() - timedelta(days=600),
        "total_development_cost": 15_000_000,
        "cost_per_unit": 250_000,
        "funding_gap": 5_000_000,
        "data_source": DataSource.FUNDER_REPORT,
        "data_quality_score": 0.65,
    },
]


def seed() -> None:
    """Create tables and insert sample data."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        # Check if data already exists
        existing = db.query(Project).count()
        if existing > 0:
            print(f"Database already has {existing} projects. Skipping seed.")
            return

        for data in SAMPLE_PROJECTS:
            project = Project(**data)
            db.add(project)

        db.flush()

        # Add sample funding sources for first project
        projects = db.query(Project).all()
        if projects:
            p = projects[0]
            db.add(FundingSource(
                project_id=p.project_id,
                source_type=FundingSourceType.LIHTC_9PCT,
                source_name="9% LIHTC - California",
                provider_organization="California Tax Credit Allocation Committee",
                amount=12_000_000,
                status=FundingSourceStatus.CLOSED,
            ))
            db.add(FundingSource(
                project_id=p.project_id,
                source_type=FundingSourceType.CONSTRUCTION_LOAN,
                source_name="Construction Loan",
                provider_organization="Wells Fargo",
                amount=18_000_000,
                status=FundingSourceStatus.CLOSED,
                interest_rate=5.5,
                term_years=2,
            ))

            # Add sample barrier
            db.add(ProjectBarrier(
                project_id=p.project_id,
                barrier_type="parking_requirements",
                barrier_description="Required 1.5 spaces per unit, requested reduction to 0.75",
                jurisdiction="Sacramento, CA",
                friction_score=650,
                stage_encountered=BarrierStage.ENTITLEMENT,
                date_encountered=date.today() - timedelta(days=500),
                date_resolved=date.today() - timedelta(days=400),
                days_delayed=45,
                cost_impact=150_000,
                variance_required=True,
                variance_granted=True,
                resolution_strategy="Submitted parking demand study showing lower actual usage",
            ))

        db.commit()
        print(f"Seeded {len(SAMPLE_PROJECTS)} projects with funding sources and barriers.")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
