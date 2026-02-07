"""Tests for the portfolio intelligence dashboard module.

Validates dashboard generation, stage distribution computation, health
distribution, geographic breakdown, velocity metrics, at-risk
identification, and empty-portfolio handling.
"""

import uuid
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from src.analytics.portfolio_intelligence import (
    _compute_geographic_breakdown,
    _compute_health_distribution,
    _compute_stage_distribution,
    _empty_dashboard,
    _identify_at_risk_projects,
    _projects_expected_co,
    _projects_expected_groundbreaking,
    generate_portfolio_dashboard,
)
from src.models.enums import (
    BuildingType,
    FundingSourceStatus,
    FundingSourceType,
    OverallHealth,
    PipelineStage,
    StakeholderType,
)
from src.models.funding_source import FundingSource
from src.models.project import Project


# ---------------------------------------------------------------------------
# Stage distribution computation
# ---------------------------------------------------------------------------


class TestComputeStageDistribution:
    """Test the per-stage project/unit aggregation."""

    def test_single_stage(self, project_factory):
        """All projects in one stage should produce a single entry."""
        projects = [
            project_factory(
                current_stage=PipelineStage.ENTITLEMENT,
                total_units=50,
                affordable_units=45,
                days_in_current_stage=100,
            ),
            project_factory(
                current_stage=PipelineStage.ENTITLEMENT,
                total_units=80,
                affordable_units=72,
                days_in_current_stage=200,
            ),
        ]

        result = _compute_stage_distribution(projects)
        assert len(result) == 1
        assert result[0]["stage"] == "entitlement"
        assert result[0]["project_count"] == 2
        assert result[0]["total_units"] == 130
        assert result[0]["affordable_units"] == 117
        assert result[0]["median_days_in_stage"] == 150.0

    def test_multiple_stages(self, project_factory):
        """Projects across stages should produce multiple entries."""
        project_factory(current_stage=PipelineStage.CONCEPT, total_units=30)
        project_factory(current_stage=PipelineStage.FINANCING, total_units=60)

        projects = [
            project_factory(current_stage=PipelineStage.CONCEPT, total_units=30),
            project_factory(current_stage=PipelineStage.FINANCING, total_units=60),
        ]

        result = _compute_stage_distribution(projects)
        stages = {sd["stage"] for sd in result}
        assert "concept" in stages
        assert "financing" in stages

    def test_empty_projects_list(self):
        """Empty project list should give empty result."""
        assert _compute_stage_distribution([]) == []


# ---------------------------------------------------------------------------
# Health distribution computation
# ---------------------------------------------------------------------------


class TestComputeHealthDistribution:
    """Test health status grouping."""

    def test_mixed_health_statuses(self, project_factory):
        """Projects with different health should produce multiple entries."""
        projects = [
            project_factory(overall_health=OverallHealth.ON_TRACK, total_units=50),
            project_factory(overall_health=OverallHealth.ON_TRACK, total_units=60),
            project_factory(overall_health=OverallHealth.AT_RISK, total_units=40),
            project_factory(overall_health=OverallHealth.DELAYED, total_units=30),
        ]

        result = _compute_health_distribution(projects)
        health_map = {hd["health_status"]: hd for hd in result}

        assert health_map["on_track"]["project_count"] == 2
        assert health_map["on_track"]["total_units"] == 110
        assert health_map["at_risk"]["project_count"] == 1
        assert health_map["delayed"]["project_count"] == 1

    def test_percentages_sum_to_100(self, project_factory):
        """Percentages across all health statuses should sum to ~100."""
        projects = [
            project_factory(overall_health=OverallHealth.ON_TRACK),
            project_factory(overall_health=OverallHealth.AT_RISK),
            project_factory(overall_health=OverallHealth.DELAYED),
            project_factory(overall_health=OverallHealth.STALLED),
        ]

        result = _compute_health_distribution(projects)
        total_pct = sum(hd["percentage"] for hd in result)
        assert abs(total_pct - 100.0) < 1.0

    def test_empty_projects(self):
        """Empty list should produce empty result."""
        assert _compute_health_distribution([]) == []


# ---------------------------------------------------------------------------
# Geographic breakdown
# ---------------------------------------------------------------------------


class TestComputeGeographicBreakdown:
    """Test jurisdiction-level geographic aggregation."""

    def test_groups_by_jurisdiction(self, project_factory):
        """Should group projects by jurisdiction."""
        projects = [
            project_factory(jurisdiction="City of Oakland", total_units=50, health_score=80.0),
            project_factory(jurisdiction="City of Oakland", total_units=70, health_score=60.0),
            project_factory(jurisdiction="City of Berkeley", total_units=40, health_score=90.0),
        ]

        result = _compute_geographic_breakdown(projects)
        geo_map = {g["area"]: g for g in result}

        assert "City of Oakland" in geo_map
        assert geo_map["City of Oakland"]["project_count"] == 2
        assert geo_map["City of Oakland"]["total_units"] == 120
        assert geo_map["City of Oakland"]["average_health_score"] == 70.0

    def test_at_risk_counted(self, project_factory):
        """At-risk/delayed/stalled projects should increment at_risk_count."""
        projects = [
            project_factory(
                jurisdiction="City of Oakland",
                overall_health=OverallHealth.AT_RISK,
            ),
            project_factory(
                jurisdiction="City of Oakland",
                overall_health=OverallHealth.DELAYED,
            ),
            project_factory(
                jurisdiction="City of Oakland",
                overall_health=OverallHealth.ON_TRACK,
            ),
        ]

        result = _compute_geographic_breakdown(projects)
        oakland = next(g for g in result if g["area"] == "City of Oakland")
        assert oakland["at_risk_count"] == 2


# ---------------------------------------------------------------------------
# At-risk project identification
# ---------------------------------------------------------------------------


class TestIdentifyAtRiskProjects:
    """Test at-risk project identification."""

    def test_only_at_risk_included(self, project_factory):
        """Only projects with at_risk/delayed/stalled health should appear."""
        projects = [
            project_factory(
                overall_health=OverallHealth.ON_TRACK,
                health_score=90.0,
            ),
            project_factory(
                overall_health=OverallHealth.AT_RISK,
                health_score=55.0,
                funding_gap=3_000_000.0,
            ),
            project_factory(
                overall_health=OverallHealth.STALLED,
                health_score=10.0,
            ),
        ]

        result = _identify_at_risk_projects(projects)
        assert len(result) == 2
        # Sorted by health_score ascending (worst first)
        assert result[0]["health_score"] == 10.0
        assert result[1]["health_score"] == 55.0

    def test_on_track_excluded(self, project_factory):
        """On-track projects should not appear in at-risk list."""
        projects = [
            project_factory(overall_health=OverallHealth.ON_TRACK),
        ]
        result = _identify_at_risk_projects(projects)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Expected CO / groundbreaking projections
# ---------------------------------------------------------------------------


class TestProjectionCounts:
    """Test CO and groundbreaking projection counting."""

    def test_projects_expected_co_within_window(self, project_factory):
        """Projects with predicted_co within 12m should be counted."""
        projects = [
            project_factory(
                predicted_co=date.today() + timedelta(days=180),
                total_units=50,
            ),
            project_factory(
                predicted_co=date.today() + timedelta(days=400),
                total_units=60,
            ),
            project_factory(predicted_co=None, total_units=70),
        ]

        count, units = _projects_expected_co(projects, months=12)
        assert count == 1
        assert units == 50

    def test_groundbreaking_within_window(self, project_factory):
        """Projects with predicted_groundbreaking within 6m should be counted."""
        projects = [
            project_factory(
                predicted_groundbreaking=date.today() + timedelta(days=90),
            ),
            project_factory(
                predicted_groundbreaking=date.today() + timedelta(days=300),
            ),
        ]

        count = _projects_expected_groundbreaking(projects, months=6)
        assert count == 1


# ---------------------------------------------------------------------------
# Empty dashboard
# ---------------------------------------------------------------------------


class TestEmptyDashboard:
    """Test the empty dashboard factory."""

    def test_empty_dashboard_structure(self):
        """Empty dashboard should have all required keys with zero values."""
        result = _empty_dashboard(None, "Test", StakeholderType.CITY)

        assert result["total_projects"] == 0
        assert result["total_units"] == 0
        assert result["stage_distribution"] == []
        assert result["health_distribution"] == []
        assert result["funding_breakdown"] == []
        assert result["at_risk_projects"] == []
        assert result["stalled_projects"] == []
        assert result["portfolio_name"] == "Test"
        assert result["stakeholder_type"] == "city"

    def test_empty_dashboard_has_velocity(self):
        """Empty dashboard should still include velocity metrics."""
        result = _empty_dashboard(None, "Test", StakeholderType.FUNDER)
        assert result["velocity"]["throughput_units_per_month"] == 0.0


# ---------------------------------------------------------------------------
# Full dashboard generation (integration)
# ---------------------------------------------------------------------------


class TestGeneratePortfolioDashboard:
    """Integration tests for the portfolio dashboard generator."""

    @pytest.fixture()
    def portfolio_projects(self, db, project_factory, funding_source_factory):
        """Create a portfolio of projects in various stages."""
        p1 = project_factory(
            project_name="Downtown Apts",
            jurisdiction="Portland, OR",
            city="Portland",
            state="OR",
            total_units=80,
            affordable_units=72,
            current_stage=PipelineStage.CONSTRUCTION,
            overall_health=OverallHealth.ON_TRACK,
            health_score=85.0,
            total_development_cost=30_000_000,
        )
        p2 = project_factory(
            project_name="Hillside Senior",
            jurisdiction="Portland, OR",
            city="Portland",
            state="OR",
            total_units=60,
            affordable_units=60,
            current_stage=PipelineStage.ENTITLEMENT,
            overall_health=OverallHealth.AT_RISK,
            health_score=55.0,
            funding_gap=3_000_000,
        )
        p3 = project_factory(
            project_name="River View Family",
            jurisdiction="Portland, OR",
            city="Portland",
            state="OR",
            total_units=45,
            affordable_units=45,
            current_stage=PipelineStage.FINANCING,
            overall_health=OverallHealth.ON_TRACK,
            health_score=78.0,
        )

        funding_source_factory(
            p1.project_id,
            source_type=FundingSourceType.LIHTC_9PCT,
            source_name="9% LIHTC",
            amount=10_000_000,
            status=FundingSourceStatus.CLOSED,
        )
        return [p1, p2, p3]

    def test_dashboard_summary(self, db, portfolio_projects):
        """Dashboard should include correct project and unit totals."""
        result = generate_portfolio_dashboard(
            db,
            jurisdiction="Portland, OR",
            stakeholder_type=StakeholderType.CITY,
        )
        assert result["total_projects"] >= 3
        assert result["total_units"] >= 185

    def test_dashboard_stage_distribution(self, db, portfolio_projects):
        """Dashboard should include stage distribution."""
        result = generate_portfolio_dashboard(
            db,
            jurisdiction="Portland, OR",
            stakeholder_type=StakeholderType.CITY,
        )
        assert len(result["stage_distribution"]) >= 1
        stages = {sd["stage"] for sd in result["stage_distribution"]}
        assert "construction" in stages or "entitlement" in stages

    def test_dashboard_health_distribution(self, db, portfolio_projects):
        """Dashboard should include health distribution."""
        result = generate_portfolio_dashboard(
            db,
            jurisdiction="Portland, OR",
            stakeholder_type=StakeholderType.CITY,
        )
        assert len(result["health_distribution"]) >= 1

    def test_dashboard_at_risk_projects(self, db, portfolio_projects):
        """Dashboard should identify at-risk projects."""
        result = generate_portfolio_dashboard(
            db,
            jurisdiction="Portland, OR",
            stakeholder_type=StakeholderType.CITY,
        )
        assert len(result["at_risk_projects"]) >= 1
        at_risk_names = [ar["project_name"] for ar in result["at_risk_projects"]]
        assert "Hillside Senior" in at_risk_names

    def test_empty_jurisdiction_returns_empty_dashboard(self, db):
        """Nonexistent jurisdiction should return empty dashboard."""
        result = generate_portfolio_dashboard(
            db,
            jurisdiction="Nonexistent, XX",
            stakeholder_type=StakeholderType.CITY,
        )
        assert result["total_projects"] == 0
        assert result["stage_distribution"] == []
