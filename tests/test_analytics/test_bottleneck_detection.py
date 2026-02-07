"""Tests for bottleneck detection and analysis.

Validates that the bottleneck analysis endpoints and helper functions
correctly identify stage accumulation, barrier impacts, and
jurisdiction friction rankings.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session

from src.api.endpoints.analytics import (
    _compute_barrier_summaries,
    _compute_jurisdiction_friction,
    _compute_stage_bottlenecks,
)
from src.models.enums import (
    BarrierStage,
    BuildingType,
    NeighborOpposition,
    OverallHealth,
    PipelineStage,
)
from src.models.project import Project


# ---------------------------------------------------------------------------
# Stage bottleneck computation
# ---------------------------------------------------------------------------


class TestStageBottlenecks:
    """Test the per-stage bottleneck aggregation."""

    def test_empty_database_returns_zero_totals(self, db):
        """With no projects, stage bottlenecks should all be zero."""
        results, total_active = _compute_stage_bottlenecks(
            db, stall_threshold_days=180, jurisdiction=None, state=None,
        )
        assert total_active == 0
        for stage_bn in results:
            assert stage_bn.project_count == 0

    def test_single_project_counted_in_correct_stage(self, db, project_factory):
        """A single entitlement-stage project should appear in entitlement stats."""
        project_factory(
            current_stage=PipelineStage.ENTITLEMENT,
            days_in_current_stage=100,
            stage_entry_date=date.today() - timedelta(days=100),
        )

        results, total_active = _compute_stage_bottlenecks(
            db, stall_threshold_days=180, jurisdiction=None, state=None,
        )
        assert total_active == 1
        entitlement_bn = next(
            r for r in results if r.stage == PipelineStage.ENTITLEMENT
        )
        assert entitlement_bn.project_count == 1
        assert entitlement_bn.avg_days is not None

    def test_stall_threshold_detection(self, db, project_factory):
        """Projects exceeding stall threshold should be counted as stalled."""
        project_factory(
            current_stage=PipelineStage.FINANCING,
            days_in_current_stage=250,
            stage_entry_date=date.today() - timedelta(days=250),
        )
        project_factory(
            current_stage=PipelineStage.FINANCING,
            days_in_current_stage=50,
            stage_entry_date=date.today() - timedelta(days=50),
        )

        results, total_active = _compute_stage_bottlenecks(
            db, stall_threshold_days=180, jurisdiction=None, state=None,
        )
        financing_bn = next(
            r for r in results if r.stage == PipelineStage.FINANCING
        )
        assert financing_bn.project_count == 2
        assert financing_bn.stalled_count == 1

    def test_jurisdiction_filter_applies(self, db, project_factory):
        """Jurisdiction filter should limit results."""
        project_factory(
            current_stage=PipelineStage.CONSTRUCTION,
            jurisdiction="City of Oakland",
        )
        project_factory(
            current_stage=PipelineStage.CONSTRUCTION,
            jurisdiction="City of Berkeley",
        )

        results, total_active = _compute_stage_bottlenecks(
            db,
            stall_threshold_days=180,
            jurisdiction="City of Oakland",
            state=None,
        )
        assert total_active == 1

    def test_percentage_of_pipeline_computed(self, db, project_factory):
        """pct_of_pipeline should sum to approximately 100 across stages."""
        for _ in range(3):
            project_factory(current_stage=PipelineStage.ENTITLEMENT)
        for _ in range(2):
            project_factory(current_stage=PipelineStage.FINANCING)

        results, total_active = _compute_stage_bottlenecks(
            db, stall_threshold_days=180, jurisdiction=None, state=None,
        )
        assert total_active == 5
        total_pct = sum(r.pct_of_pipeline for r in results)
        assert abs(total_pct - 100.0) < 1.0  # Rounding tolerance


# ---------------------------------------------------------------------------
# Barrier summary computation
# ---------------------------------------------------------------------------


class TestBarrierSummaries:
    """Test barrier aggregation across projects."""

    def test_empty_barriers_returns_empty_list(self, db):
        """No barriers in DB should yield an empty list."""
        results = _compute_barrier_summaries(
            db, jurisdiction=None, state=None, top_n=10,
        )
        assert results == []

    def test_barrier_aggregation(self, db, project_factory, barrier_factory):
        """Barriers should be aggregated by type with correct totals."""
        p1 = project_factory()
        p2 = project_factory()

        barrier_factory(
            p1.project_id,
            barrier_type="Minimum Parking Requirements",
            days_delayed=45,
            cost_impact=250_000.00,
            jurisdiction="City of Oakland",
        )
        barrier_factory(
            p2.project_id,
            barrier_type="Minimum Parking Requirements",
            days_delayed=60,
            cost_impact=300_000.00,
            jurisdiction="City of Berkeley",
        )
        barrier_factory(
            p1.project_id,
            barrier_type="Height Limit Restriction",
            days_delayed=90,
            cost_impact=500_000.00,
            jurisdiction="City of Oakland",
        )

        results = _compute_barrier_summaries(
            db, jurisdiction=None, state=None, top_n=10,
        )
        assert len(results) == 2

        # Parking barrier should be present with 2 occurrences
        parking = next(
            (r for r in results if r.barrier_type == "Minimum Parking Requirements"),
            None,
        )
        assert parking is not None
        assert parking.occurrence_count == 2
        assert parking.total_days_delayed == 105
        assert parking.affected_jurisdictions == 2

    def test_barrier_jurisdiction_filter(self, db, project_factory, barrier_factory):
        """Filtering by jurisdiction should limit barrier results."""
        p1 = project_factory()
        barrier_factory(
            p1.project_id,
            barrier_type="Setback Requirements",
            days_delayed=30,
            jurisdiction="City of Oakland",
        )
        barrier_factory(
            p1.project_id,
            barrier_type="Setback Requirements",
            days_delayed=40,
            jurisdiction="City of Berkeley",
        )

        results = _compute_barrier_summaries(
            db, jurisdiction="City of Oakland", state=None, top_n=10,
        )
        assert len(results) == 1
        assert results[0].total_days_delayed == 30

    def test_top_n_limits_results(self, db, project_factory, barrier_factory):
        """The top_n parameter should cap the number of results returned."""
        p = project_factory()
        for i in range(5):
            barrier_factory(
                p.project_id,
                barrier_type=f"Barrier Type {i}",
                days_delayed=(i + 1) * 10,
            )

        results = _compute_barrier_summaries(
            db, jurisdiction=None, state=None, top_n=3,
        )
        assert len(results) == 3


# ---------------------------------------------------------------------------
# Jurisdiction friction ranking
# ---------------------------------------------------------------------------


class TestJurisdictionFriction:
    """Test jurisdiction-level friction analysis."""

    def test_empty_database_returns_empty(self, db):
        """No projects should yield an empty jurisdiction list."""
        results = _compute_jurisdiction_friction(db, state=None, top_n=10)
        assert results == []

    def test_jurisdiction_aggregation(self, db, project_factory):
        """Projects should be grouped and ranked by jurisdiction friction."""
        project_factory(
            jurisdiction="City of Oakland",
            jurisdiction_friction_score=70,
            overall_health=OverallHealth.AT_RISK,
            current_stage=PipelineStage.ENTITLEMENT,
            entitlement_duration_days=300,
        )
        project_factory(
            jurisdiction="City of Oakland",
            jurisdiction_friction_score=60,
            overall_health=OverallHealth.ON_TRACK,
            current_stage=PipelineStage.FINANCING,
            entitlement_duration_days=200,
        )
        project_factory(
            jurisdiction="City of Berkeley",
            jurisdiction_friction_score=40,
            overall_health=OverallHealth.ON_TRACK,
            current_stage=PipelineStage.CONSTRUCTION,
            entitlement_duration_days=150,
        )

        results = _compute_jurisdiction_friction(db, state=None, top_n=10)
        assert len(results) == 2

        # Oakland should rank higher (higher avg friction)
        assert results[0].jurisdiction == "City of Oakland"
        assert results[0].project_count == 2
        assert results[0].avg_friction_score == 65.0
        assert results[0].at_risk_count == 1

    def test_state_filter_applies(self, db, project_factory):
        """State filter should limit jurisdiction friction results."""
        project_factory(
            jurisdiction="City of Oakland",
            state="CA",
            jurisdiction_friction_score=60,
        )
        project_factory(
            jurisdiction="City of Portland",
            state="OR",
            jurisdiction_friction_score=50,
        )

        results = _compute_jurisdiction_friction(db, state="CA", top_n=10)
        assert len(results) == 1
        assert results[0].jurisdiction == "City of Oakland"
