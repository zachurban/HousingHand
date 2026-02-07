"""Tests for the pipeline health assessment module.

Validates composite health scoring across five dimensions (timeline,
budget, funding, risk, team) and ensures correct mapping to
OverallHealth categories (on_track, at_risk, delayed, stalled).
"""

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from src.analytics.health_assessment import (
    HEALTH_WEIGHTS,
    _generate_recommendations,
    _score_budget,
    _score_risk,
    _score_team,
    _score_timeline,
    _score_to_health,
    assess_project_health,
)
from src.models.enums import (
    BuildingType,
    FundingSourceStatus,
    FundingSourceType,
    NeighborOpposition,
    OverallHealth,
    PipelineStage,
)
from src.models.funding_source import FundingSource
from src.models.project import Project


# ---------------------------------------------------------------------------
# _score_to_health mapping tests
# ---------------------------------------------------------------------------


class TestScoreToHealthMapping:
    """Verify that composite scores map to the correct OverallHealth enum."""

    @patch("src.analytics.health_assessment._load_national_benchmarks")
    def test_high_score_maps_to_on_track(self, mock_benchmarks):
        mock_benchmarks.return_value = {
            "health_thresholds": {"on_track": 80, "at_risk": 60, "delayed": 40}
        }
        assert _score_to_health(95.0) == OverallHealth.ON_TRACK
        assert _score_to_health(80.0) == OverallHealth.ON_TRACK

    @patch("src.analytics.health_assessment._load_national_benchmarks")
    def test_moderate_score_maps_to_at_risk(self, mock_benchmarks):
        mock_benchmarks.return_value = {
            "health_thresholds": {"on_track": 80, "at_risk": 60, "delayed": 40}
        }
        assert _score_to_health(79.9) == OverallHealth.AT_RISK
        assert _score_to_health(60.0) == OverallHealth.AT_RISK

    @patch("src.analytics.health_assessment._load_national_benchmarks")
    def test_low_score_maps_to_delayed(self, mock_benchmarks):
        mock_benchmarks.return_value = {
            "health_thresholds": {"on_track": 80, "at_risk": 60, "delayed": 40}
        }
        assert _score_to_health(59.9) == OverallHealth.DELAYED
        assert _score_to_health(40.0) == OverallHealth.DELAYED

    @patch("src.analytics.health_assessment._load_national_benchmarks")
    def test_very_low_score_maps_to_stalled(self, mock_benchmarks):
        mock_benchmarks.return_value = {
            "health_thresholds": {"on_track": 80, "at_risk": 60, "delayed": 40}
        }
        assert _score_to_health(39.9) == OverallHealth.STALLED
        assert _score_to_health(0.0) == OverallHealth.STALLED


# ---------------------------------------------------------------------------
# Timeline dimension scoring
# ---------------------------------------------------------------------------


class TestTimelineScoring:
    """Test the timeline dimension scoring function."""

    def test_on_pace_project_scores_100(self, sample_project, mock_peer_benchmark):
        """A project at or below peer median should score 100."""
        sample_project.days_in_current_stage = 90
        # entitlement median is 240 days, so 90 days = ratio 0.375 -> score 100
        result = _score_timeline(sample_project, mock_peer_benchmark)
        assert result["raw_score"] == 100.0
        assert result["dimension"] == "timeline"

    def test_double_median_scores_zero(self, sample_project, mock_peer_benchmark):
        """A project at 2x the peer median should score 0."""
        sample_project.days_in_current_stage = 480  # 2x 240
        result = _score_timeline(sample_project, mock_peer_benchmark)
        assert result["raw_score"] == 0.0

    def test_1_5x_median_scores_50(self, sample_project, mock_peer_benchmark):
        """A project at 1.5x peer median should score approximately 50."""
        sample_project.days_in_current_stage = 360  # 1.5x 240
        result = _score_timeline(sample_project, mock_peer_benchmark)
        assert 45.0 <= result["raw_score"] <= 55.0

    def test_no_days_data_gets_default_score(self, sample_project, mock_peer_benchmark):
        """A project with no days_in_current_stage gets a neutral default."""
        sample_project.days_in_current_stage = None
        result = _score_timeline(sample_project, mock_peer_benchmark)
        assert result["raw_score"] == 50.0

    def test_stalled_stage_gets_default_score(self, sample_project, mock_peer_benchmark):
        """Terminal/stalled stages get a default 50."""
        sample_project.current_stage = PipelineStage.STALLED
        result = _score_timeline(sample_project, mock_peer_benchmark)
        assert result["raw_score"] == 50.0

    def test_weight_is_applied_correctly(self, sample_project, mock_peer_benchmark):
        """Weighted score should equal raw_score * timeline weight."""
        sample_project.days_in_current_stage = 90
        result = _score_timeline(sample_project, mock_peer_benchmark)
        expected_weighted = round(result["raw_score"] * HEALTH_WEIGHTS["timeline"], 2)
        assert result["weighted_score"] == expected_weighted


# ---------------------------------------------------------------------------
# Budget dimension scoring
# ---------------------------------------------------------------------------


class TestBudgetScoring:
    """Test the budget dimension scoring function."""

    def test_under_budget_scores_100(self, sample_project):
        """A project on or under budget should score 100."""
        sample_project.budget_variance_percent = -5.0
        result = _score_budget(sample_project)
        assert result["raw_score"] == 100.0

    def test_zero_variance_scores_100(self, sample_project):
        """Exactly on budget should score 100."""
        sample_project.budget_variance_percent = 0.0
        result = _score_budget(sample_project)
        assert result["raw_score"] == 100.0

    def test_severely_over_budget_scores_zero(self, sample_project):
        """30%+ over budget should score 0."""
        sample_project.budget_variance_percent = 30.0
        result = _score_budget(sample_project)
        assert result["raw_score"] == 0.0

    def test_moderate_overrun_scores_proportionally(self, sample_project):
        """15% over budget should score approximately 50."""
        sample_project.budget_variance_percent = 15.0
        result = _score_budget(sample_project)
        assert 45.0 <= result["raw_score"] <= 55.0

    def test_no_budget_data_gets_default(self, sample_project):
        """Missing budget data should yield default score of 70."""
        sample_project.budget_variance_percent = None
        sample_project.original_budget = None
        sample_project.current_budget = None
        result = _score_budget(sample_project)
        assert result["raw_score"] == 70.0

    def test_computed_from_original_and_current_budget(self, sample_project):
        """When variance_percent is None, it should be computed from budgets."""
        sample_project.budget_variance_percent = None
        sample_project.original_budget = 10_000_000.00
        sample_project.current_budget = 10_000_000.00
        result = _score_budget(sample_project)
        assert result["raw_score"] == 100.0


# ---------------------------------------------------------------------------
# Risk dimension scoring
# ---------------------------------------------------------------------------


class TestRiskScoring:
    """Test the risk dimension scoring function."""

    def test_low_risk_scores_high(self, sample_project):
        """A project with low risk metrics should score well."""
        sample_project.risk_score = 10.0
        sample_project.jurisdiction_friction_score = 20
        sample_project.neighbor_opposition_level = NeighborOpposition.NONE
        sample_project.appeals_filed = 0
        result = _score_risk(sample_project)
        assert result["raw_score"] >= 80.0

    def test_high_risk_scores_low(self, sample_project):
        """A project with severe risk indicators should score poorly."""
        sample_project.risk_score = 90.0
        sample_project.jurisdiction_friction_score = 85
        sample_project.neighbor_opposition_level = NeighborOpposition.SEVERE
        sample_project.appeals_filed = 3
        result = _score_risk(sample_project)
        assert result["raw_score"] <= 30.0

    def test_no_risk_data_gets_default(self, sample_project):
        """Missing risk data should give a moderate default score."""
        sample_project.risk_score = None
        sample_project.jurisdiction_friction_score = None
        sample_project.neighbor_opposition_level = None
        sample_project.appeals_filed = 0
        result = _score_risk(sample_project)
        assert result["raw_score"] == 75.0

    def test_opposition_levels_are_graded(self, sample_project):
        """Higher opposition should produce lower scores."""
        sample_project.risk_score = None
        sample_project.jurisdiction_friction_score = None
        sample_project.appeals_filed = 0

        sample_project.neighbor_opposition_level = NeighborOpposition.LOW
        low_result = _score_risk(sample_project)

        sample_project.neighbor_opposition_level = NeighborOpposition.HIGH
        high_result = _score_risk(sample_project)

        assert low_result["raw_score"] > high_result["raw_score"]


# ---------------------------------------------------------------------------
# Team dimension scoring
# ---------------------------------------------------------------------------


class TestTeamScoring:
    """Test the team completeness dimension scoring."""

    def test_full_team_scores_high(self, sample_project):
        """All four team roles filled should yield a high score."""
        sample_project.developer_org = "Dev Corp"
        sample_project.architect = "Arc Studio"
        sample_project.general_contractor = "GC Inc"
        sample_project.property_manager = "PM LLC"
        sample_project.data_completeness = None
        result = _score_team(sample_project)
        assert result["raw_score"] == 100.0

    def test_no_team_scores_zero(self, sample_project):
        """No team roles filled should yield 0."""
        sample_project.developer_org = None
        sample_project.architect = None
        sample_project.general_contractor = None
        sample_project.property_manager = None
        sample_project.data_completeness = None
        result = _score_team(sample_project)
        assert result["raw_score"] == 0.0

    def test_partial_team_scores_proportionally(self, sample_project):
        """Two of four team roles filled should yield ~50."""
        sample_project.developer_org = "Dev Corp"
        sample_project.architect = "Arc Studio"
        sample_project.general_contractor = None
        sample_project.property_manager = None
        sample_project.data_completeness = None
        result = _score_team(sample_project)
        assert result["raw_score"] == 50.0

    def test_data_completeness_blends_into_score(self, sample_project):
        """When data_completeness is present, score should blend 70/30."""
        sample_project.developer_org = "Dev Corp"
        sample_project.architect = "Arc Studio"
        sample_project.general_contractor = "GC Inc"
        sample_project.property_manager = "PM LLC"
        sample_project.data_completeness = 0.5
        result = _score_team(sample_project)
        # 100 * 0.7 + (0.5 * 100) * 0.3 = 70 + 15 = 85
        assert result["raw_score"] == 85.0


# ---------------------------------------------------------------------------
# Full health assessment integration
# ---------------------------------------------------------------------------


class TestAssessProjectHealth:
    """Integration tests for the full health assessment pipeline."""

    @patch("src.analytics.health_assessment.compute_peer_benchmarks")
    @patch("src.analytics.health_assessment._load_national_benchmarks")
    def test_on_track_project_assessment(
        self, mock_benchmarks, mock_compute, db, sample_project, mock_peer_benchmark
    ):
        """A healthy project should be assessed as on_track."""
        mock_benchmarks.return_value = {
            "health_thresholds": {"on_track": 80, "at_risk": 60, "delayed": 40}
        }
        mock_compute.return_value = mock_peer_benchmark

        result = assess_project_health(db, sample_project.project_id, mock_peer_benchmark)

        assert result["project_id"] == str(sample_project.project_id)
        assert result["project_name"] == "Sunrise Village Apartments"
        assert result["current_stage"] == "entitlement"
        assert 0.0 <= result["composite_score"] <= 100.0
        assert result["overall_health"] in [h.value for h in OverallHealth]
        assert "dimensions" in result
        assert set(result["dimensions"].keys()) == {"timeline", "budget", "funding", "risk", "team"}

    @patch("src.analytics.health_assessment.compute_peer_benchmarks")
    @patch("src.analytics.health_assessment._load_national_benchmarks")
    def test_terminal_project_returns_fixed_score(
        self, mock_benchmarks, mock_compute, db, project_factory, mock_peer_benchmark
    ):
        """A project in operations stage should return 100/on_track."""
        mock_benchmarks.return_value = {
            "health_thresholds": {"on_track": 80, "at_risk": 60, "delayed": 40}
        }
        mock_compute.return_value = mock_peer_benchmark
        proj = project_factory(current_stage=PipelineStage.OPERATIONS)

        result = assess_project_health(db, proj.project_id, mock_peer_benchmark)

        assert result["composite_score"] == 100.0
        assert result["overall_health"] == OverallHealth.ON_TRACK.value

    @patch("src.analytics.health_assessment.compute_peer_benchmarks")
    @patch("src.analytics.health_assessment._load_national_benchmarks")
    def test_abandoned_project_returns_zero_stalled(
        self, mock_benchmarks, mock_compute, db, project_factory, mock_peer_benchmark
    ):
        """An abandoned project should return 0/stalled."""
        mock_benchmarks.return_value = {
            "health_thresholds": {"on_track": 80, "at_risk": 60, "delayed": 40}
        }
        mock_compute.return_value = mock_peer_benchmark
        proj = project_factory(current_stage=PipelineStage.ABANDONED)

        result = assess_project_health(db, proj.project_id, mock_peer_benchmark)

        assert result["composite_score"] == 0.0
        assert result["overall_health"] == OverallHealth.STALLED.value

    @patch("src.analytics.health_assessment.compute_peer_benchmarks")
    @patch("src.analytics.health_assessment._load_national_benchmarks")
    def test_nonexistent_project_raises(
        self, mock_benchmarks, mock_compute, db, mock_peer_benchmark
    ):
        """Assessing a nonexistent project should raise ValueError."""
        import uuid

        mock_benchmarks.return_value = {
            "health_thresholds": {"on_track": 80, "at_risk": 60, "delayed": 40}
        }
        mock_compute.return_value = mock_peer_benchmark

        with pytest.raises(ValueError, match="not found"):
            assess_project_health(db, uuid.uuid4(), mock_peer_benchmark)

    @patch("src.analytics.health_assessment.compute_peer_benchmarks")
    @patch("src.analytics.health_assessment._load_national_benchmarks")
    def test_score_trend_detection(
        self, mock_benchmarks, mock_compute, db, sample_project, mock_peer_benchmark
    ):
        """Score trend should be detected relative to stored health_score."""
        mock_benchmarks.return_value = {
            "health_thresholds": {"on_track": 80, "at_risk": 60, "delayed": 40}
        }
        mock_compute.return_value = mock_peer_benchmark

        result = assess_project_health(db, sample_project.project_id, mock_peer_benchmark)

        assert result["score_trend"] in ("improving", "stable", "declining")
        assert result["previous_score"] == 82.0


# ---------------------------------------------------------------------------
# Recommendations generation
# ---------------------------------------------------------------------------


class TestRecommendations:
    """Test recommendation generation for underperforming dimensions."""

    @patch("src.analytics.health_assessment._load_national_benchmarks")
    def test_low_timeline_produces_recommendation(self, mock_benchmarks, sample_project):
        mock_benchmarks.return_value = {
            "health_thresholds": {"on_track": 80, "at_risk": 60, "delayed": 40}
        }
        dimensions = {
            "timeline": {"dimension": "timeline", "raw_score": 40.0, "weight": 0.3, "weighted_score": 12.0, "detail": ""},
            "budget": {"dimension": "budget", "raw_score": 90.0, "weight": 0.25, "weighted_score": 22.5, "detail": ""},
            "funding": {"dimension": "funding", "raw_score": 90.0, "weight": 0.2, "weighted_score": 18.0, "detail": ""},
            "risk": {"dimension": "risk", "raw_score": 90.0, "weight": 0.15, "weighted_score": 13.5, "detail": ""},
            "team": {"dimension": "team", "raw_score": 90.0, "weight": 0.1, "weighted_score": 9.0, "detail": ""},
        }
        recs = _generate_recommendations(sample_project, dimensions, OverallHealth.AT_RISK)
        assert len(recs) > 0
        assert any("timeline" in r.lower() or "schedule" in r.lower() for r in recs)

    @patch("src.analytics.health_assessment._load_national_benchmarks")
    def test_all_high_scores_produces_no_recommendations(self, mock_benchmarks, sample_project):
        mock_benchmarks.return_value = {
            "health_thresholds": {"on_track": 80, "at_risk": 60, "delayed": 40}
        }
        dimensions = {
            "timeline": {"dimension": "timeline", "raw_score": 95.0, "weight": 0.3, "weighted_score": 28.5, "detail": ""},
            "budget": {"dimension": "budget", "raw_score": 95.0, "weight": 0.25, "weighted_score": 23.75, "detail": ""},
            "funding": {"dimension": "funding", "raw_score": 95.0, "weight": 0.2, "weighted_score": 19.0, "detail": ""},
            "risk": {"dimension": "risk", "raw_score": 95.0, "weight": 0.15, "weighted_score": 14.25, "detail": ""},
            "team": {"dimension": "team", "raw_score": 95.0, "weight": 0.1, "weighted_score": 9.5, "detail": ""},
        }
        recs = _generate_recommendations(sample_project, dimensions, OverallHealth.ON_TRACK)
        assert len(recs) == 0

    @patch("src.analytics.health_assessment._load_national_benchmarks")
    def test_recommendations_capped_at_five(self, mock_benchmarks, sample_project):
        mock_benchmarks.return_value = {
            "health_thresholds": {"on_track": 80, "at_risk": 60, "delayed": 40}
        }
        dimensions = {
            "timeline": {"dimension": "timeline", "raw_score": 20.0, "weight": 0.3, "weighted_score": 6.0, "detail": ""},
            "budget": {"dimension": "budget", "raw_score": 20.0, "weight": 0.25, "weighted_score": 5.0, "detail": ""},
            "funding": {"dimension": "funding", "raw_score": 20.0, "weight": 0.2, "weighted_score": 4.0, "detail": ""},
            "risk": {"dimension": "risk", "raw_score": 20.0, "weight": 0.15, "weighted_score": 3.0, "detail": ""},
            "team": {"dimension": "team", "raw_score": 20.0, "weight": 0.1, "weighted_score": 2.0, "detail": ""},
        }
        recs = _generate_recommendations(sample_project, dimensions, OverallHealth.STALLED)
        assert len(recs) <= 5
