"""City and county permit database scrapers."""

import logging
from datetime import date

from src.integrations.public_records import PermitRecord, PermitScraper

logger = logging.getLogger(__name__)


class GenericPermitScraper(PermitScraper):
    """Generic permit scraper for jurisdictions with standard APIs.

    This scraper handles the common pattern of city open-data portals
    that expose permit data through Socrata or similar APIs.
    """

    async def search_permits(
        self,
        address: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        permit_type: str | None = None,
    ) -> list[PermitRecord]:
        """Search permits using a Socrata-style open data API."""
        params: dict = {}
        filters = []

        if address:
            filters.append(f"upper(address) like upper('%{address}%')")
        if date_from:
            filters.append(f"issue_date >= '{date_from.isoformat()}'")
        if date_to:
            filters.append(f"issue_date <= '{date_to.isoformat()}'")
        if permit_type:
            filters.append(f"permit_type = '{permit_type}'")

        if filters:
            params["$where"] = " AND ".join(filters)

        params["$limit"] = 100
        params["$order"] = "issue_date DESC"

        try:
            response = await self._client.get(self.base_url, params=params)
            response.raise_for_status()
            records = response.json()

            return [
                PermitRecord(
                    permit_number=r.get("permit_number", ""),
                    address=r.get("address", ""),
                    jurisdiction=self.jurisdiction,
                    permit_type=r.get("permit_type", ""),
                    status=r.get("status", ""),
                    issue_date=r.get("issue_date", ""),
                    description=r.get("description", ""),
                    units=int(r.get("units", 0) or 0),
                    valuation=float(r.get("valuation", 0) or 0),
                )
                for r in records
            ]
        except Exception:
            logger.exception(f"Error searching permits for {self.jurisdiction}")
            return []


def get_scraper_for_jurisdiction(jurisdiction: str) -> PermitScraper | None:
    """Factory function to get the appropriate scraper for a jurisdiction.

    Returns None if no scraper is configured for the given jurisdiction.
    """
    # Registry of known jurisdiction scrapers and their API endpoints.
    # Extend this mapping as new jurisdictions are onboarded.
    registry: dict[str, str] = {}

    base_url = registry.get(jurisdiction.lower())
    if base_url:
        return GenericPermitScraper(jurisdiction=jurisdiction, base_url=base_url)
    return None
