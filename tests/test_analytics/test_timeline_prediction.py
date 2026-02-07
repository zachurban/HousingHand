"""Tests for the analytics timeline prediction module.

Validates single-project predictions, friction-to-multiplier conversion,
risk adjustments, remaining-stage calculation, and terminal project
handling.
"""

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from src.analytics.timeline_prediction import (
    _friction_to_multiplier,
    _get_remaining_stages,
    _risk_to_multiplier,
    predict_project_timeline,
)
from src.models.enums import (
    BuildingType,
    NeighborOpposition,
    OverallHealth,
    PipelineStage,
)
from src.models.project import Project


# ---------------------------------------------------------------------------
# Friction-to-multiplier conversion
# ---------------------------------------------------------------------------


class TestFrictionToMultiplier:
    """Test the friction score to duration multiplier mapping."""

    def test_median_friction_is_1x(self):
        """A friction score of 50 (median) should produce 1.0x multiplier."""
        assert _friction_to_multiplier(50) == 1.0

    def test_high_friction_increases_multiplier(self):
        """A friction score of 100 should produce approximately 1.8x."""
        result = _friction_to_multiplier(100)
        assert result == pytest.approx(1.8, abs=0.05)

    def test_low_friction_decreases_multiplier(self):
        """A friction score of 1 should produce approximately 0.7x."""
        result = _friction_to_multiplier(1)
        assert result == pytest.approx(0.706, abs=0.05)

    def test_none_friction_returns_1x(self):
        """None friction score should default to 1.0x."""
        assert _friction_to_multiplier(None) == 1.0

    def test_multiplier_is_monotonic(self):
        """Higher friction should always produce a higher multiplier."""
        prev = _friction_to_multiplier(1)
        for score in range(10, 101, 10):
            current = _friction_to_multiplier(score)
            assert current >= prev, (
                f"Multiplier decreased from score {score - 10} to {score}"
            )
            prev = current


# ---------------------------------------------------------------------------
# Risk-to-multiplier conversion
# ---------------------------------------------------------------------------


class TestRiskToMultiplier:
    """Test the project risk factor to duration multiplier mapping."""

    def test_low_risk_project(self, sample_project):
        """A low-risk project should have a multiplier near 1.0."""
        sample_project.risk_score = 15.0
        sample_project.appeals_filed = 0
        sample_project.neighbor_opposition_level = NeighborOpposition.NONE
        sample_project.design_review_iterations = 1
        result = _risk_to_multiplier(sample_project)
        assert 0.8 <= result <= 1.1

    def test_high_risk_project(self, sample_project):
        """A high-risk project should have an elevated multiplier."""
        sample_project.risk_score = 90.0
        sample_project.appeals_filed = 3
        sample_project.neighbor_opposition_level = NeighborOpposition.SEVERE
        sample_project.design_review_iterations = 6
        result = _risk_to_multiplier(sample_project)
        assert result > 1.2

    def test_no_risk_data_returns_1x(self, sample_project):
        """A project with no risk data should default to 1.0."""
        sample_project.risk_score = None
        sample_project.appeals_filed = 0
        sample_project.neighbor_opposition_level = None
        sample_project.design_review_iterations = 0
        assert _risk_to_multiplier(sample_project) == 1.0

    def test_multiplier_is_capped(self, sample_project):
        """Multiplier should not exceed 1.5 regardless of inputs."""
        sample_project.risk_score = 100.0
        sample_project.appeals_filed = 10
        sample_project.neighbor_opposition_level = NeighborOpposition.SEVERE
        sample_project.design_review_iterations = 20
        result = _risk_to_multiplier(sample_project)
        assert result <= 1.5


# ---------------------------------------------------------------------------
# Remaining stages calculation
# ---------------------------------------------------------------------------


class TestGetRemainingStages:
    """Test the remaining stages computation."""

    def test_concept_returns_all_stages(self):
        """A concept-stage project should have all stages remaining."""
        remaining = _get_remaining_stages("concept")
        assert remaining == [
            "concept", "pre_development", "entitlement",
            "financing", "construction", "lease_up",
        ]

    def test_construction_returns_construction_and_beyond(self):
        """A construction-stage project should return construction + lease_up."""
        remaining = _get_remaining_stages("construction")
        assert remaining == ["construction", "lease_up"]

    def test_lease_up_returns_only_lease_up(self):
        """A lease_up-stage project should return just lease_up."""
        remaining = _get_remaining_stages("lease_up")
        assert remaining == ["lease_up"]

    def test_unknown_stage_returns_full_pipeline(self):
        """An unknown stage should return the full pipeline."""
        remaining = _get_remaining_stages("something_weird")
        assert len(remaining) == 6


# ---------------------------------------------------------------------------
# Single project prediction (integration)
# ---------------------------------------------------------------------------


class TestPredictProjectTimeline:
    """Integration tests for predict_project_timeline."""

    @patch("src.analytics.timeline_prediction._load_national_benchmarks")
    @patch("src.analytics.timeline_prediction.compute_peer_benchmarks")
    def test_entitlement_project_prediction(
        self, mock_compute, mock_benchmarks, db, sample_project, mock_peer_benchmark
    ):
        """A mid-pipeline project should get stage-by-stage predictions."""
        mock_compute.return_value = mock_peer_benchmark
        mock_benchmarks.return_value = {
            "stage_durations": {
                "entitlement": {"median": 240},
                "financing": {"median": 180},
                "construction": {"median": 540},
                "lease_up": {"median": 120},
            },
            "holding_costs": {"daily_per_unit_during_entitlement": 20},
        }

        result = predict_project_timeline(
            db, sample_project.project_id, mock_peer_benchmark
        )

        assert result["project_id"] == str(sample_project.project_id)
        assert result["current_stage"] == "entitlement"
        assert result["predicted_remaining_days"] > 0
        assert 0.0 < result["confidence"] <= 1.0
        assert len(result["stage_predictions"]) >= 1
        assert result["method"] in ("peer_adjusted", "national_adjusted")

    @patch("src.analytics.timeline_prediction._load_national_benchmarks")
    @patch("src.analytics.timeline_prediction.compute_peer_benchmarks")
    def test_terminal_project_returns_zero_remaining(
        self, mock_compute, mock_benchmarks, db, project_factory, mock_peer_benchmark
    ):
        """A project in operations should predict 0 remaining days."""
        mock_compute.return_value = mock_peer_benchmark
        mock_benchmarks.return_value = {"stage_durations": {}, "holding_costs": {}}
        proj = project_factory(current_stage=PipelineStage.OPERATIONS)

        result = predict_project_timeline(
            db, proj.project_id, mock_peer_benchmark
        )

        assert result["predicted_remaining_days"] == 0.0
        assert result["method"] == "terminal"
        assert result["confidence"] == 1.0

    @patch("src.analytics.timeline_prediction._load_national_benchmarks")
    @patch("src.analytics.timeline_prediction.compute_peer_benchmarks")
    def test_nonexistent_project_raises(
        self, mock_compute, mock_benchmarks, db, mock_peer_benchmark
    ):
        """Predicting for a nonexistent project should raise ValueError."""
        import uuid
        mock_compute.return_value = mock_peer_benchmark
        mock_benchmarks.return_value = {"stage_durations": {}, "holding_costs": {}}

        with pytest.raises(ValueError, match="not found"):
            predict_project_timeline(db, uuid.uuid4(), mock_peer_benchmark)

    @patch("src.analytics.timeline_prediction._load_national_benchmarks")
    @patch("src.analytics.timeline_prediction.compute_peer_benchmarks")
    def test_prediction_includes_confidence_interval(
        self, mock_compute, mock_benchmarks, db, sample_project, mock_peer_benchmark
    ):
        """Prediction should include a confidence interval tuple."""
        mock_compute.return_value = mock_peer_benchmark
        mock_benchmarks.return_value = {
            "stage_durations": {"entitlement": {"median": 240}},
            "holding_costs": {},
        }

        result = predict_project_timeline(
            db, sample_project.project_id, mock_peer_benchmark
        )

        ci = result["confidence_interval_days"]
        assert isinstance(ci, tuple)
        assert len(ci) == 2
        low, high = ci
        assert low <= high

    @patch("src.analytics.timeline_prediction._load_national_benchmarks")
    @patch("src.analytics.timeline_prediction.compute_peer_benchmarks")
    def test_high_friction_extends_prediction(
        self, mock_compute, mock_benchmarks, db, project_factory, mock_peer_benchmark
    ):
        """Higher friction scores should produce longer predictions."""
        mock_compute.return_value = mock_peer_benchmark
        mock_benchmarks.return_value = {
            "stage_durations": {"entitlement": {"median": 240}},
            "holding_costs": {},
        }

        low_friction = project_factory(
            current_stage=PipelineStage.ENTITLEMENT,
            jurisdiction_friction_score=20,
            days_in_current_stage=0,
        )
        high_friction = project_factory(
            current_stage=PipelineStage.ENTITLEMENT,
            jurisdiction_friction_score=90,
            days_in_current_stage=0,
        )

        result_low = predict_project_timeline(
            db, low_friction.project_id, mock_peer_benchmark
        )
        result_high = predict_project_timeline(
            db, high_friction.project_id, mock_peer_benchmark
        )

        assert (
            result_high["predicted_remaining_days"]
            > result_low["predicted_remaining_days"]
        )

    @patch("src.analytics.timeline_prediction._load_national_benchmarks")
    @patch("src.analytics.timeline_prediction.compute_peer_benchmarks")
    def test_days_in_stage_subtracted_from_current_stage(
        self, mock_compute, mock_benchmarks, db, project_factory, mock_peer_benchmark
    ):
        """Days already spent in current stage should be subtracted."""
        mock_compute.return_value = mock_peer_benchmark
        mock_benchmarks.return_value = {
            "stage_durations": {"entitlement": {"median": 240}},
            "holding_costs": {},
        }

        fresh = project_factory(
            current_stage=PipelineStage.ENTITLEMENT,
            days_in_current_stage=0,
            jurisdiction_friction_score=50,
        )
        midway = project_factory(
            current_stage=PipelineStage.ENTITLEMENT,
            days_in_current_stage=120,
            jurisdiction_friction_score=50,
        )

        result_fresh = predict_project_timeline(
            db, fresh.project_id, mock_peer_benchmark
        )
        result_midway = predict_project_timeline(
            db, midway.project_id, mock_peer_benchmark
        )

        assert (
            result_midway["predicted_remaining_days"]
            < result_fresh["predicted_remaining_days"]
        )
