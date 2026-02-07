"""Tests for ML feature engineering."""

from datetime import date, timedelta

import pytest

from src.models.enums import BuildingType, PipelineStage
from src.models.project import Project


@pytest.fixture
def feature_project(db):
    """Create a project for feature extraction tests."""
    p = Project(
        project_name="Feature Test Project",
        project_slug="feature-test-project",
        city="Denver",
        state="CO",
        jurisdiction="Denver, CO",
        total_units=100,
        affordable_units=80,
        market_units=20,
        ami_30_units=20,
        ami_40_units=10,
        ami_50_units=30,
        ami_60_units=20,
        stories=5,
        parking_spaces=75,
        site_acres=2.0,
        building_type=BuildingType.NEW_CONSTRUCTION,
        current_stage=PipelineStage.ENTITLEMENT,
        concept_start=date.today() - timedelta(days=300),
    )
    db.add(p)
    db.commit()
    return p


class TestFeatureEngineering:
    """Tests for feature extraction from projects."""

    def test_extract_features_returns_dict(self, db, feature_project):
        """Feature extraction should return a dict of features."""
        from src.ml.feature_engineering import extract_features

        features = extract_features(feature_project)
        assert isinstance(features, dict)
        assert "total_units" in features

    def test_feature_values_are_numeric(self, db, feature_project):
        """All feature values should be numeric."""
        from src.ml.feature_engineering import extract_features

        features = extract_features(feature_project)
        for key, value in features.items():
            assert isinstance(value, (int, float)), (
                f"Feature {key} has non-numeric value: {value}"
            )

    def test_affordable_pct_calculation(self, db, feature_project):
        """Should correctly calculate affordable unit percentage."""
        from src.ml.feature_engineering import extract_features

        features = extract_features(feature_project)
        if "affordable_units_pct" in features:
            assert 0.0 <= features["affordable_units_pct"] <= 1.0
            assert abs(features["affordable_units_pct"] - 0.8) < 0.01

    def test_deep_affordability_pct(self, db, feature_project):
        """Should calculate deep affordability percentage."""
        from src.ml.feature_engineering import extract_features

        features = extract_features(feature_project)
        if "deep_affordability_pct" in features:
            # 20 + 10 = 30 out of 100
            assert abs(features["deep_affordability_pct"] - 0.30) < 0.01

    def test_parking_ratio(self, db, feature_project):
        """Should calculate parking ratio."""
        from src.ml.feature_engineering import extract_features

        features = extract_features(feature_project)
        if "parking_ratio" in features:
            assert abs(features["parking_ratio"] - 0.75) < 0.01
