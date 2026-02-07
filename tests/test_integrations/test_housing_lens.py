"""Tests for HousingLens integration client."""

import pytest

from src.integrations.housing_lens import (
    FrictionTopic,
    HousingLensClient,
    JurisdictionFrictionData,
)


class TestJurisdictionFrictionData:
    """Tests for the JurisdictionFrictionData dataclass."""

    def test_get_topic_score_existing(self):
        """Should return score for an existing topic."""
        data = JurisdictionFrictionData(
            jurisdiction="TestCity, CA",
            overall_score=650,
            topics=[
                FrictionTopic(
                    name="parking_requirements",
                    friction_score=720,
                    jurisdiction_rank=15,
                ),
                FrictionTopic(
                    name="design_review",
                    friction_score=500,
                    jurisdiction_rank=42,
                ),
            ],
        )
        assert data.get_topic_score("parking_requirements") == 720
        assert data.get_topic_score("design_review") == 500

    def test_get_topic_score_missing(self):
        """Should return 0 for a non-existent topic."""
        data = JurisdictionFrictionData(
            jurisdiction="TestCity, CA",
            overall_score=650,
            topics=[],
        )
        assert data.get_topic_score("nonexistent") == 0

    def test_get_topic_existing(self):
        """Should return FrictionTopic object for an existing topic."""
        topic = FrictionTopic(
            name="zoning_variances",
            friction_score=800,
            jurisdiction_rank=5,
        )
        data = JurisdictionFrictionData(
            jurisdiction="TestCity, CA",
            overall_score=700,
            topics=[topic],
        )
        result = data.get_topic("zoning_variances")
        assert result is not None
        assert result.friction_score == 800

    def test_get_topic_missing(self):
        """Should return None for a non-existent topic."""
        data = JurisdictionFrictionData(
            jurisdiction="TestCity, CA",
            overall_score=700,
            topics=[],
        )
        assert data.get_topic("nonexistent") is None


class TestHousingLensClient:
    """Tests for HousingLensClient initialization."""

    def test_client_creation(self):
        """Should create client with custom URL and key."""
        client = HousingLensClient(
            base_url="http://test:8001/api/v1",
            api_key="test-key",
        )
        assert client.base_url == "http://test:8001/api/v1"
        assert client.api_key == "test-key"
