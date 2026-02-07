"""Shared pytest fixtures for the HousingHand test suite.

Provides an in-memory SQLite database, session management, and factory
functions for creating sample projects, funding sources, and barriers.
"""

import uuid
from collections.abc import Generator
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.connection import Base

# Force all models to be registered on Base.metadata before create_all.
from src.models.project import Project  # noqa: F401
from src.models.funding_source import FundingSource  # noqa: F401
from src.models.barrier import ProjectBarrier  # noqa: F401
from src.models.peer_group import PeerGroup  # noqa: F401
from src.models.portfolio import PortfolioDashboard  # noqa: F401
from src.models.reform import PolicyReform  # noqa: F401
from src.models.enums import (
    BarrierStage,
    BuildingType,
    DataSource,
    FundingSourceStatus,
    FundingSourceType,
    NeighborOpposition,
    OverallHealth,
    PipelineStage,
    PortfolioType,
    ReformType,
    StructureType,
)


# ---------------------------------------------------------------------------
# Engine & session fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def engine():
    """Create an in-memory SQLite engine shared across the entire test session."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture()
def db(engine) -> Generator[Session, None, None]:
    """Yield a database session that is rolled back after each test.

    Every test gets a clean transactional boundary so that data created
    inside one test never leaks into another.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _make_project_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def sample_project(db: Session) -> Project:
    """Insert and return a single realistic sample project.

    This represents a mid-pipeline LIHTC new-construction project in
    Oakland, CA that is currently in the entitlement stage.
    """
    project = Project(
        project_id=_make_project_id(),
        project_name="Sunrise Village Apartments",
        project_slug=f"sunrise-village-apartments-{uuid.uuid4().hex[:8]}",
        address="1234 Main Street",
        city="Oakland",
        county="Alameda",
        state="CA",
        zip="94607",
        latitude=37.8044,
        longitude=-122.2712,
        jurisdiction="City of Oakland",
        neighborhood="West Oakland",
        census_tract="4001.00",
        developer_org="Community Housing Partners",
        developer_contact="Jane Doe",
        architect="Studio Architecture",
        general_contractor="BuildRight Construction",
        property_manager="GreenField Management",
        site_acres=2.5,
        building_type=BuildingType.NEW_CONSTRUCTION,
        structure_type=StructureType.WOOD_FRAME,
        stories=4,
        parking_spaces=60,
        total_units=120,
        affordable_units=108,
        market_units=12,
        studio_units=10,
        one_br_units=40,
        two_br_units=50,
        three_br_units=15,
        four_plus_br_units=5,
        ami_30_units=24,
        ami_40_units=12,
        ami_50_units=36,
        ami_60_units=36,
        ami_80_units=0,
        market_rate_units=12,
        senior_units=0,
        family_units=120,
        psf_units=0,
        veteran_units=0,
        homeless_set_aside=10,
        current_stage=PipelineStage.ENTITLEMENT,
        stage_entry_date=date.today() - timedelta(days=90),
        days_in_current_stage=90,
        overall_health=OverallHealth.ON_TRACK,
        health_score=82.0,
        last_milestone_date=date.today() - timedelta(days=30),
        next_milestone_date=date.today() + timedelta(days=60),
        next_milestone_type="Design Review Hearing",
        concept_start=date(2023, 1, 15),
        concept_complete=date(2023, 4, 1),
        concept_duration_days=76,
        pre_development_start=date(2023, 4, 1),
        pre_development_complete=date(2023, 10, 15),
        pre_development_duration_days=197,
        entitlement_start=date(2023, 10, 15),
        total_development_cost=42_000_000.00,
        cost_per_unit=350_000.00,
        cost_per_square_foot=450.00,
        land_acquisition_cost=6_000_000.00,
        hard_costs=28_000_000.00,
        soft_costs=5_000_000.00,
        original_budget=40_000_000.00,
        current_budget=42_000_000.00,
        budget_variance_dollars=2_000_000.00,
        budget_variance_percent=5.0,
        total_funding_committed=35_000_000.00,
        funding_gap=7_000_000.00,
        jurisdiction_friction_score=45,
        neighbor_opposition_level=NeighborOpposition.LOW,
        appeals_filed=0,
        risk_score=25.0,
        data_source=DataSource.DEVELOPER_PORTAL,
        data_quality_score=0.85,
        data_completeness=0.90,
        is_public=True,
    )
    db.add(project)
    db.flush()
    return project


@pytest.fixture()
def sample_funding_source(db: Session, sample_project: Project) -> FundingSource:
    """Insert and return a LIHTC 4% funding source attached to sample_project."""
    fs = FundingSource(
        funding_id=uuid.uuid4(),
        project_id=sample_project.project_id,
        source_type=FundingSourceType.LIHTC_4PCT,
        source_name="California LIHTC 4%",
        provider_organization="California Tax Credit Allocation Committee",
        amount=15_000_000.00,
        status=FundingSourceStatus.COMMITTED,
        application_date=date(2023, 6, 1),
        award_date=date(2023, 9, 15),
        compliance_period_years=15,
        affordability_period_years=55,
    )
    db.add(fs)
    db.flush()
    return fs


@pytest.fixture()
def sample_barrier(db: Session, sample_project: Project) -> ProjectBarrier:
    """Insert and return a zoning barrier attached to sample_project."""
    barrier = ProjectBarrier(
        barrier_id=uuid.uuid4(),
        project_id=sample_project.project_id,
        barrier_type="Minimum Parking Requirements",
        barrier_description="City requires 1.5 spaces/unit; project designed for 0.5 spaces/unit.",
        jurisdiction="City of Oakland",
        friction_score=65,
        jurisdiction_rank=12,
        stage_encountered=BarrierStage.ENTITLEMENT,
        date_encountered=date(2024, 1, 15),
        days_delayed=45,
        cost_impact=250_000.00,
        resolution_strategy="Applied for parking variance citing transit proximity.",
        variance_required=True,
        variance_granted=None,
        appeal_filed=False,
    )
    db.add(barrier)
    db.flush()
    return barrier


# ---------------------------------------------------------------------------
# Multi-project factory
# ---------------------------------------------------------------------------

@pytest.fixture()
def project_factory(db: Session):
    """Return a callable that creates projects with customizable overrides.

    Usage in tests::

        p = project_factory(project_name="Test", current_stage=PipelineStage.FINANCING)
    """

    def _create(**overrides) -> Project:
        defaults = dict(
            project_id=_make_project_id(),
            project_name=f"Test Project {uuid.uuid4().hex[:6]}",
            project_slug=f"test-project-{uuid.uuid4().hex[:8]}",
            city="Oakland",
            state="CA",
            jurisdiction="City of Oakland",
            total_units=100,
            affordable_units=90,
            market_units=10,
            current_stage=PipelineStage.CONCEPT,
            building_type=BuildingType.NEW_CONSTRUCTION,
            structure_type=StructureType.WOOD_FRAME,
            stories=4,
            is_public=True,
        )
        defaults.update(overrides)
        project = Project(**defaults)
        db.add(project)
        db.flush()
        return project

    return _create


@pytest.fixture()
def funding_source_factory(db: Session):
    """Return a callable that creates funding sources with customizable overrides."""

    def _create(project_id: uuid.UUID, **overrides) -> FundingSource:
        defaults = dict(
            funding_id=uuid.uuid4(),
            project_id=project_id,
            source_type=FundingSourceType.LIHTC_4PCT,
            source_name=f"Test Funding {uuid.uuid4().hex[:6]}",
            amount=5_000_000.00,
            status=FundingSourceStatus.ANTICIPATED,
        )
        defaults.update(overrides)
        fs = FundingSource(**defaults)
        db.add(fs)
        db.flush()
        return fs

    return _create


@pytest.fixture()
def barrier_factory(db: Session):
    """Return a callable that creates barriers with customizable overrides."""

    def _create(project_id: uuid.UUID, **overrides) -> ProjectBarrier:
        defaults = dict(
            barrier_id=uuid.uuid4(),
            project_id=project_id,
            barrier_type="Generic Regulatory Barrier",
            jurisdiction="City of Oakland",
            friction_score=50,
            days_delayed=30,
            cost_impact=100_000.00,
            stage_encountered=BarrierStage.ENTITLEMENT,
        )
        defaults.update(overrides)
        barrier = ProjectBarrier(**defaults)
        db.add(barrier)
        db.flush()
        return barrier

    return _create


# ---------------------------------------------------------------------------
# Peer benchmark mock fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_peer_benchmark():
    """Return a PeerBenchmarkResult dict with realistic national benchmark data.

    This avoids hitting the YAML config or running peer queries during tests.
    """
    from src.analytics.peer_benchmarking import PeerBenchmarkResult, StageBenchmark

    return PeerBenchmarkResult(
        peer_group_id=None,
        peer_group_name="test_national_benchmarks",
        project_count=0,
        stage_benchmarks={
            "concept": StageBenchmark(
                stage="concept", median_days=60.0, mean_days=65.0,
                p25_days=30.0, p75_days=90.0, p90_days=120.0,
                std_days=25.0, sample_size=50,
            ),
            "pre_development": StageBenchmark(
                stage="pre_development", median_days=180.0, mean_days=190.0,
                p25_days=120.0, p75_days=270.0, p90_days=365.0,
                std_days=60.0, sample_size=50,
            ),
            "entitlement": StageBenchmark(
                stage="entitlement", median_days=240.0, mean_days=260.0,
                p25_days=150.0, p75_days=365.0, p90_days=540.0,
                std_days=80.0, sample_size=50,
            ),
            "financing": StageBenchmark(
                stage="financing", median_days=180.0, mean_days=195.0,
                p25_days=120.0, p75_days=270.0, p90_days=365.0,
                std_days=55.0, sample_size=50,
            ),
            "construction": StageBenchmark(
                stage="construction", median_days=540.0, mean_days=560.0,
                p25_days=365.0, p75_days=720.0, p90_days=900.0,
                std_days=120.0, sample_size=50,
            ),
            "lease_up": StageBenchmark(
                stage="lease_up", median_days=120.0, mean_days=130.0,
                p25_days=60.0, p75_days=180.0, p90_days=270.0,
                std_days=40.0, sample_size=50,
            ),
        },
        median_total_duration_days=1320.0,
        median_cost_per_unit=350_000.0,
        p25_cost_per_unit=250_000.0,
        p75_cost_per_unit=475_000.0,
        computed_at=datetime.utcnow().isoformat(),
    )
