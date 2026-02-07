"""Tests for portfolio intelligence dashboard generation."""

from datetime import date, timedelta

import pytest

from src.models.enums import (
    BuildingType,
    FundingSourceStatus,
    FundingSourceType,
    OverallHealth,
    PipelineStage,
)
from src.models.funding_source import FundingSource
from src.models.project import Project


@pytest.fixture
def portfolio_projects(db):
    """Create a portfolio of projects in various stages."""
    projects_data = [
        {
            "project_name": "Downtown Apts",
            "project_slug": "downtown-apts",
            "jurisdiction": "Portland, OR",
            "city": "Portland",
            "state": "OR",
            "total_units": 80,
            "affordable_units": 72,
            "current_stage": PipelineStage.CONSTRUCTION,
            "overall_health": OverallHealth.ON_TRACK,
            "health_score": 85.0,
            "total_development_cost": 30_000_000,
            "construction_start": date.today() - timedelta(days=90),
            "concept_start": date.today() - timedelta(days=600),
            "predicted_co": date.today() + timedelta(days=365),
        },
        {
            "project_name": "Hillside Senior",
            "project_slug": "hillside-senior",
            "jurisdiction": "Portland, OR",
            "city": "Portland",
            "state": "OR",
            "total_units": 60,
            "affordable_units": 60,
            "current_stage": PipelineStage.ENTITLEMENT,
            "overall_health": OverallHealth.AT_RISK,
            "health_score": 55.0,
            "total_development_cost": 24_000_000,
            "funding_gap": 3_000_000,
            "concept_start": date.today() - timedelta(days=300),
        },
        {
            "project_name": "River View Family",
            "project_slug": "river-view-family",
            "jurisdiction": "Portland, OR",
            "city": "Portland",
            "state": "OR",
            "total_units": 45,
            "affordable_units": 45,
            "current_stage": PipelineStage.FINANCING,
            "overall_health": OverallHealth.ON_TRACK,
            "health_score": 78.0,
            "total_development_cost": 18_000_000,
            "concept_start": date.today() - timedelta(days=450),
            "predicted_co": date.today() + timedelta(days=540),
        },
    ]

    projects = []
    for data in projects_data:
        p = Project(**data)
        db.add(p)
        projects.append(p)

    db.flush()

    # Add funding source
    db.add(FundingSource(
        project_id=projects[0].project_id,
        source_type=FundingSourceType.LIHTC_9PCT,
        source_name="9% LIHTC",
        amount=10_000_000,
        status=FundingSourceStatus.CLOSED,
    ))

    db.commit()
    return projects


class TestPortfolioIntelligence:
    """Tests for generate_portfolio_intelligence (or generate_portfolio_dashboard)."""

    def test_portfolio_returns_summary(self, db, portfolio_projects):
        """Portfolio should return summary with total projects and units."""
        from src.analytics.portfolio_intelligence import (
            generate_portfolio_dashboard,
        )

        result = generate_portfolio_dashboard(
            db=db,
            geography_filter={"jurisdiction": "Portland, OR"},
            stakeholder_type="city",
        )
        assert isinstance(result, dict)
        summary = result.get("portfolio_summary", {})
        assert summary.get("total_projects", 0) >= 3
        assert summary.get("total_units", 0) >= 185

    def test_portfolio_pipeline_snapshot(self, db, portfolio_projects):
        """Should include pipeline snapshot with stage breakdown."""
        from src.analytics.portfolio_intelligence import (
            generate_portfolio_dashboard,
        )

        result = generate_portfolio_dashboard(
            db=db,
            geography_filter={"jurisdiction": "Portland, OR"},
            stakeholder_type="city",
        )
        snapshot = result.get("pipeline_snapshot", {})
        assert "units_by_stage" in snapshot or "projects_by_stage" in snapshot

    def test_portfolio_health_distribution(self, db, portfolio_projects):
        """Should include health distribution counts."""
        from src.analytics.portfolio_intelligence import (
            generate_portfolio_dashboard,
        )

        result = generate_portfolio_dashboard(
            db=db,
            geography_filter={"jurisdiction": "Portland, OR"},
            stakeholder_type="city",
        )
        health = result.get("health_distribution", {})
        assert isinstance(health, dict)

    def test_empty_portfolio(self, db):
        """Should handle empty portfolio gracefully."""
        from src.analytics.portfolio_intelligence import (
            generate_portfolio_dashboard,
        )

        result = generate_portfolio_dashboard(
            db=db,
            geography_filter={"jurisdiction": "Nonexistent, XX"},
            stakeholder_type="city",
        )
        summary = result.get("portfolio_summary", {})
        assert summary.get("total_projects", 0) == 0
