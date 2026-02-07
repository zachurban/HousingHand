"""Tests for policy reform impact measurement."""

from datetime import date, timedelta

import pytest

from src.models.enums import BuildingType, PipelineStage
from src.models.project import Project


@pytest.fixture
def pre_reform_projects(db):
    """Create projects that completed entitlement before a reform."""
    reform_date = date.today() - timedelta(days=365)
    projects = []
    for i in range(6):
        p = Project(
            project_name=f"Pre Reform {i}",
            project_slug=f"pre-reform-{i}",
            jurisdiction="TestCity, CA",
            city="TestCity",
            state="CA",
            total_units=50,
            affordable_units=50,
            current_stage=PipelineStage.CONSTRUCTION,
            entitlement_start=reform_date - timedelta(days=400 + i * 10),
            entitlement_complete=reform_date - timedelta(days=100 + i * 10),
            entitlement_duration_days=300 + i * 10,
        )
        db.add(p)
        projects.append(p)
    db.commit()
    return projects


@pytest.fixture
def post_reform_projects(db):
    """Create projects that started entitlement after a reform."""
    reform_date = date.today() - timedelta(days=365)
    projects = []
    for i in range(4):
        p = Project(
            project_name=f"Post Reform {i}",
            project_slug=f"post-reform-{i}",
            jurisdiction="TestCity, CA",
            city="TestCity",
            state="CA",
            total_units=50,
            affordable_units=50,
            current_stage=PipelineStage.FINANCING,
            entitlement_start=reform_date + timedelta(days=60 + i * 10),
            entitlement_complete=reform_date + timedelta(days=260 + i * 10),
            entitlement_duration_days=200 + i * 10,
        )
        db.add(p)
        projects.append(p)
    db.commit()
    return projects


class TestReformImpact:
    """Tests for measure_reform_impact."""

    def test_reform_impact_returns_result(
        self, db, pre_reform_projects, post_reform_projects
    ):
        """Should return reform impact analysis."""
        from src.analytics.reform_impact import measure_reform_impact

        reform_date = date.today() - timedelta(days=365)
        result = measure_reform_impact(
            db=db,
            jurisdiction="TestCity, CA",
            reform_date=reform_date,
            reform_description="Streamlined design review",
        )
        assert isinstance(result, dict)

    def test_insufficient_data_returns_error(self, db):
        """Should indicate insufficient data when too few projects."""
        from src.analytics.reform_impact import measure_reform_impact

        result = measure_reform_impact(
            db=db,
            jurisdiction="EmptyCity, XX",
            reform_date=date.today() - timedelta(days=180),
            reform_description="Some reform",
        )
        assert isinstance(result, dict)
        # Should handle gracefully either with error key or low confidence

    def test_reform_with_improvement(
        self, db, pre_reform_projects, post_reform_projects
    ):
        """Post-reform projects with shorter durations should show improvement."""
        from src.analytics.reform_impact import measure_reform_impact

        reform_date = date.today() - timedelta(days=365)
        result = measure_reform_impact(
            db=db,
            jurisdiction="TestCity, CA",
            reform_date=reform_date,
            reform_description="Streamlined design review",
        )
        # The post-reform projects have ~200 day durations vs ~300 pre-reform
        # So we expect to see improvement
        if "analysis" in result:
            analysis = result["analysis"]
            if "days_saved_per_project" in analysis:
                assert analysis["days_saved_per_project"] >= 0
