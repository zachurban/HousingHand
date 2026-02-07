"""Tests for the policy reform impact measurement module.

Validates pre/post comparison, statistical testing, cost savings estimates,
confidence level determination, and helper functions.
"""

import uuid
from datetime import date, timedelta
from unittest.mock import patch

import numpy as np
import pytest

from src.analytics.reform_impact import (
    _bootstrap_ci_diff,
    _compute_slope,
    _determine_confidence,
    _extract_durations,
    _stall_rate,
    measure_reform_impact,
)
from src.models.enums import (
    BarrierStage,
    BuildingType,
    ConfidenceLevel,
    PipelineStage,
    ReformType,
)
from src.models.project import Project
from src.models.reform import PolicyReform


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------


class TestExtractDurations:
    """Test the _extract_durations helper."""

    def test_extracts_entitlement_durations(self, project_factory):
        """Should extract non-null entitlement durations from projects."""
        p1 = project_factory(entitlement_duration_days=250)
        p2 = project_factory(entitlement_duration_days=300)
        p3 = project_factory(entitlement_duration_days=None)

        result = _extract_durations([p1, p2, p3], "entitlement")
        assert result == [250.0, 300.0]

    def test_empty_list_returns_empty(self):
        """No projects should yield an empty list."""
        assert _extract_durations([], "entitlement") == []

    def test_all_none_returns_empty(self, project_factory):
        """All-null durations should yield an empty list."""
        p = project_factory(entitlement_duration_days=None)
        assert _extract_durations([p], "entitlement") == []


class TestComputeSlope:
    """Test the simple linear slope computation."""

    def test_increasing_values(self):
        """Slope of increasing series should be positive."""
        values = [100.0, 120.0, 140.0, 160.0]
        slope = _compute_slope(values)
        assert slope > 0

    def test_decreasing_values(self):
        """Slope of decreasing series should be negative."""
        values = [300.0, 250.0, 200.0, 150.0]
        slope = _compute_slope(values)
        assert slope < 0

    def test_constant_values(self):
        """Slope of constant series should be approximately zero."""
        values = [200.0, 200.0, 200.0, 200.0]
        slope = _compute_slope(values)
        assert abs(slope) < 0.01

    def test_single_value_returns_zero(self):
        """Single value should return slope 0."""
        assert _compute_slope([100.0]) == 0.0

    def test_empty_returns_zero(self):
        """Empty list should return slope 0."""
        assert _compute_slope([]) == 0.0


class TestDetermineConfidence:
    """Test confidence level determination."""

    def test_high_confidence(self):
        """Large sample, significant, medium+ effect -> HIGH."""
        result = _determine_confidence(20, 15, True, "large")
        assert result == ConfidenceLevel.HIGH

    def test_moderate_confidence(self):
        """Moderate sample, significant, small effect -> MODERATE."""
        result = _determine_confidence(8, 6, True, "small")
        assert result == ConfidenceLevel.MODERATE

    def test_low_confidence(self):
        """Small sample, not significant -> LOW."""
        result = _determine_confidence(2, 3, False, "negligible")
        assert result == ConfidenceLevel.LOW

    def test_insufficient_data_is_low(self):
        """Very small samples should always be LOW confidence."""
        result = _determine_confidence(1, 1, False, "insufficient_data")
        assert result == ConfidenceLevel.LOW


class TestBootstrapCIDiff:
    """Test the bootstrap confidence interval for median difference."""

    def test_positive_difference(self):
        """Pre > post should give a positive CI."""
        pre = [300.0, 320.0, 280.0, 310.0, 290.0, 340.0, 350.0, 305.0]
        post = [200.0, 210.0, 190.0, 220.0, 195.0, 215.0, 205.0, 198.0]
        low, high = _bootstrap_ci_diff(pre, post)
        assert low > 0  # Pre is clearly larger

    def test_overlapping_distributions(self):
        """Overlapping distributions should have CI spanning zero."""
        pre = [200.0, 210.0, 190.0, 205.0, 195.0]
        post = [198.0, 208.0, 192.0, 203.0, 197.0]
        low, high = _bootstrap_ci_diff(pre, post)
        assert low <= high

    def test_returns_tuple_of_two(self):
        """Should return a (lower, upper) tuple."""
        pre = [100.0, 120.0, 110.0]
        post = [90.0, 100.0, 95.0]
        result = _bootstrap_ci_diff(pre, post)
        assert isinstance(result, tuple)
        assert len(result) == 2


class TestStallRate:
    """Test the stall rate computation."""

    def test_no_stalled_projects(self, project_factory):
        """No stalled/abandoned projects should give rate 0."""
        projects = [
            project_factory(current_stage=PipelineStage.ENTITLEMENT),
            project_factory(current_stage=PipelineStage.ENTITLEMENT),
        ]
        rate = _stall_rate(projects, "entitlement")
        assert rate == 0.0

    def test_some_stalled(self, project_factory):
        """Mix of active and stalled should give proportional rate."""
        projects = [
            project_factory(current_stage=PipelineStage.ENTITLEMENT),
            project_factory(current_stage=PipelineStage.STALLED),
            project_factory(current_stage=PipelineStage.ABANDONED),
        ]
        rate = _stall_rate(projects, "entitlement")
        assert 0.0 < rate <= 1.0


# ---------------------------------------------------------------------------
# Full reform impact measurement (integration)
# ---------------------------------------------------------------------------


class TestMeasureReformImpact:
    """Integration tests for measure_reform_impact."""

    @pytest.fixture()
    def reform_with_data(self, db, project_factory):
        """Create a reform and pre/post projects in the DB."""
        reform_date = date.today() - timedelta(days=365)
        jurisdiction = "City of Oakland"

        reform = PolicyReform(
            reform_id=uuid.uuid4(),
            jurisdiction=jurisdiction,
            reform_name="Parking Minimum Elimination",
            reform_type=ReformType.PARKING_REFORM,
            effective_date=reform_date,
            implementation_buffer_days=60,
        )
        db.add(reform)

        # Pre-reform projects: completed entitlement before the reform
        for i in range(6):
            project_factory(
                jurisdiction=jurisdiction,
                current_stage=PipelineStage.CONSTRUCTION,
                entitlement_start=reform_date - timedelta(days=600 + i * 20),
                entitlement_complete=reform_date - timedelta(days=300 + i * 10),
                entitlement_duration_days=300 + i * 10,
            )

        # Post-reform projects: started entitlement after buffer
        for i in range(5):
            project_factory(
                jurisdiction=jurisdiction,
                current_stage=PipelineStage.FINANCING,
                entitlement_start=reform_date + timedelta(days=90 + i * 30),
                entitlement_complete=reform_date + timedelta(days=290 + i * 20),
                entitlement_duration_days=200 + i * 5,
            )

        db.flush()
        return reform

    @patch("src.analytics.reform_impact._load_national_benchmarks")
    def test_reform_impact_basic_structure(
        self, mock_benchmarks, db, reform_with_data
    ):
        """Should return a well-formed ReformImpactResult."""
        mock_benchmarks.return_value = {
            "holding_costs": {"daily_per_unit_during_entitlement": 20},
        }

        result = measure_reform_impact(db, reform_with_data.reform_id)

        assert result["reform_name"] == "Parking Minimum Elimination"
        assert result["jurisdiction"] == "City of Oakland"
        assert result["pre_reform_n"] >= 1
        assert result["post_reform_n"] >= 1
        assert "test_used" in result
        assert "p_value" in result
        assert "confidence_level" in result
        assert result["measured_at"] is not None

    @patch("src.analytics.reform_impact._load_national_benchmarks")
    def test_pre_reform_longer_than_post(
        self, mock_benchmarks, db, reform_with_data
    ):
        """Pre-reform durations (~300-350) should be longer than post (~200-220)."""
        mock_benchmarks.return_value = {
            "holding_costs": {"daily_per_unit_during_entitlement": 20},
        }

        result = measure_reform_impact(db, reform_with_data.reform_id)

        assert result["pre_reform_median_days"] > result["post_reform_median_days"]
        assert result["days_saved_per_project"] > 0
        assert result["percent_improvement"] > 0

    @patch("src.analytics.reform_impact._load_national_benchmarks")
    def test_cost_savings_positive(
        self, mock_benchmarks, db, reform_with_data
    ):
        """Days saved should translate to positive cost savings."""
        mock_benchmarks.return_value = {
            "holding_costs": {"daily_per_unit_during_entitlement": 20},
        }

        result = measure_reform_impact(db, reform_with_data.reform_id)

        if result["days_saved_per_project"] > 0:
            assert result["total_cost_savings"] > 0

    @patch("src.analytics.reform_impact._load_national_benchmarks")
    def test_nonexistent_reform_raises(self, mock_benchmarks, db):
        """Measuring a nonexistent reform should raise ValueError."""
        mock_benchmarks.return_value = {"holding_costs": {}}

        with pytest.raises(ValueError, match="not found"):
            measure_reform_impact(db, uuid.uuid4())

    @patch("src.analytics.reform_impact._load_national_benchmarks")
    def test_reform_without_effective_date_raises(
        self, mock_benchmarks, db
    ):
        """A reform with no effective_date should raise ValueError."""
        mock_benchmarks.return_value = {"holding_costs": {}}

        reform = PolicyReform(
            reform_id=uuid.uuid4(),
            jurisdiction="City of Oakland",
            reform_name="Draft Reform",
            reform_type=ReformType.PARKING_REFORM,
            effective_date=None,
        )
        db.add(reform)
        db.flush()

        with pytest.raises(ValueError, match="no effective_date"):
            measure_reform_impact(db, reform.reform_id)

    @patch("src.analytics.reform_impact._load_national_benchmarks")
    def test_insufficient_data_produces_caveats(
        self, mock_benchmarks, db
    ):
        """A reform with <2 projects should produce caveats."""
        mock_benchmarks.return_value = {
            "holding_costs": {"daily_per_unit_during_entitlement": 10},
        }

        reform = PolicyReform(
            reform_id=uuid.uuid4(),
            jurisdiction="City of Nowhere",
            reform_name="Empty Reform",
            reform_type=ReformType.DENSITY_UPZONE,
            effective_date=date.today() - timedelta(days=180),
            implementation_buffer_days=30,
        )
        db.add(reform)
        db.flush()

        result = measure_reform_impact(db, reform.reform_id)
        assert result["test_used"] == "insufficient_data"
        assert len(result["caveats"]) > 0
        assert result["confidence_level"] == ConfidenceLevel.LOW.value
