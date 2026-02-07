"""Client for the HousingLens regulatory friction API."""

from dataclasses import dataclass, field

import httpx

from config.settings import get_settings


@dataclass
class FrictionTopic:
    """A single friction topic score for a jurisdiction."""

    name: str
    friction_score: int
    jurisdiction_rank: int
    national_percentile: float = 0.0
    description: str = ""


@dataclass
class JurisdictionFrictionData:
    """Aggregated friction data for a jurisdiction from HousingLens."""

    jurisdiction: str
    overall_score: int = 0
    topics: list[FrictionTopic] = field(default_factory=list)
    last_updated: str = ""

    def get_topic_score(self, topic_name: str) -> int:
        """Get friction score for a specific topic, defaulting to 0."""
        for topic in self.topics:
            if topic.name == topic_name:
                return topic.friction_score
        return 0

    def get_topic(self, topic_name: str) -> FrictionTopic | None:
        """Get a full topic object by name."""
        for topic in self.topics:
            if topic.name == topic_name:
                return topic
        return None


class HousingLensClient:
    """HTTP client for the HousingLens friction score API."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        settings = get_settings()
        self.base_url = (base_url or settings.housing_lens_api_url).rstrip("/")
        self.api_key = api_key or settings.housing_lens_api_key
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30.0,
        )

    async def get_jurisdiction_data(self, jurisdiction: str) -> JurisdictionFrictionData:
        """Fetch friction scores for a jurisdiction."""
        try:
            response = await self._client.get(
                "/jurisdictions/friction",
                params={"jurisdiction": jurisdiction},
            )
            response.raise_for_status()
            data = response.json()

            topics = [
                FrictionTopic(
                    name=t["name"],
                    friction_score=t["friction_score"],
                    jurisdiction_rank=t.get("jurisdiction_rank", 0),
                    national_percentile=t.get("national_percentile", 0.0),
                    description=t.get("description", ""),
                )
                for t in data.get("topics", [])
            ]

            return JurisdictionFrictionData(
                jurisdiction=jurisdiction,
                overall_score=data.get("overall_score", 0),
                topics=topics,
                last_updated=data.get("last_updated", ""),
            )
        except httpx.HTTPError:
            # Return empty data if HousingLens is unavailable
            return JurisdictionFrictionData(jurisdiction=jurisdiction)

    async def get_topic_scores(
        self, jurisdiction: str, topics: list[str]
    ) -> dict[str, int]:
        """Fetch specific topic friction scores for a jurisdiction."""
        data = await self.get_jurisdiction_data(jurisdiction)
        return {topic: data.get_topic_score(topic) for topic in topics}

    async def get_related_friction_topics(
        self, jurisdiction: str, reform_description: str
    ) -> list[FrictionTopic]:
        """Find friction topics related to a policy reform description."""
        try:
            response = await self._client.get(
                "/jurisdictions/related-topics",
                params={
                    "jurisdiction": jurisdiction,
                    "query": reform_description,
                },
            )
            response.raise_for_status()
            data = response.json()

            return [
                FrictionTopic(
                    name=t["name"],
                    friction_score=t["friction_score"],
                    jurisdiction_rank=t.get("jurisdiction_rank", 0),
                )
                for t in data.get("topics", [])
            ]
        except httpx.HTTPError:
            return []

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
