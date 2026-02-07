"""Client for the HousingEar policy monitoring API."""

from dataclasses import dataclass
from datetime import date

import httpx

from config.settings import get_settings


@dataclass
class FundingProgram:
    """A funding program discovered by HousingEar."""

    program_name: str
    jurisdiction: str
    amount_available: float = 0.0
    application_deadline: str = ""
    source_url: str = ""
    description: str = ""


@dataclass
class PolicyChange:
    """A policy change detected by HousingEar."""

    title: str
    jurisdiction: str
    change_type: str = ""
    effective_date: str = ""
    source_url: str = ""
    description: str = ""
    ordinance_number: str = ""


class HousingEarClient:
    """HTTP client for the HousingEar policy and funding monitoring API."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        settings = get_settings()
        self.base_url = (base_url or settings.housing_ear_api_url).rstrip("/")
        self.api_key = api_key or settings.housing_ear_api_key
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30.0,
        )

    async def check_funding_opportunities(
        self,
        jurisdiction: str,
        date_after: date | None = None,
    ) -> list[FundingProgram]:
        """Check for new funding programs available in a jurisdiction."""
        try:
            params: dict = {"jurisdiction": jurisdiction}
            if date_after:
                params["date_after"] = date_after.isoformat()

            response = await self._client.get("/funding/opportunities", params=params)
            response.raise_for_status()
            data = response.json()

            return [
                FundingProgram(
                    program_name=p["program_name"],
                    jurisdiction=p.get("jurisdiction", jurisdiction),
                    amount_available=p.get("amount_available", 0.0),
                    application_deadline=p.get("application_deadline", ""),
                    source_url=p.get("source_url", ""),
                    description=p.get("description", ""),
                )
                for p in data.get("programs", [])
            ]
        except httpx.HTTPError:
            return []

    async def get_recent_policy_changes(
        self,
        jurisdiction: str,
        days_back: int = 90,
    ) -> list[PolicyChange]:
        """Get recent policy changes in a jurisdiction."""
        try:
            response = await self._client.get(
                "/policy/changes",
                params={
                    "jurisdiction": jurisdiction,
                    "days_back": days_back,
                },
            )
            response.raise_for_status()
            data = response.json()

            return [
                PolicyChange(
                    title=c["title"],
                    jurisdiction=c.get("jurisdiction", jurisdiction),
                    change_type=c.get("change_type", ""),
                    effective_date=c.get("effective_date", ""),
                    source_url=c.get("source_url", ""),
                    description=c.get("description", ""),
                    ordinance_number=c.get("ordinance_number", ""),
                )
                for c in data.get("changes", [])
            ]
        except httpx.HTTPError:
            return []

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
