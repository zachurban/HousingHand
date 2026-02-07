"""Public records data scrapers for permit and project data."""

import logging
from dataclasses import dataclass
from datetime import date

import httpx

logger = logging.getLogger(__name__)


@dataclass
class PermitRecord:
    """A building permit record from public data."""

    permit_number: str
    address: str
    jurisdiction: str
    permit_type: str = ""
    status: str = ""
    issue_date: str = ""
    description: str = ""
    units: int = 0
    valuation: float = 0.0


@dataclass
class LIHTCProject:
    """A LIHTC project record from state HFA reports."""

    project_name: str
    address: str
    city: str
    state: str
    credit_type: str = ""  # 4% or 9%
    total_units: int = 0
    low_income_units: int = 0
    allocation_year: int = 0
    placed_in_service_date: str = ""
    total_credit: float = 0.0


class PermitScraper:
    """Base class for scraping city/county permit databases."""

    def __init__(self, jurisdiction: str, base_url: str):
        self.jurisdiction = jurisdiction
        self.base_url = base_url
        self._client = httpx.AsyncClient(timeout=60.0)

    async def search_permits(
        self,
        address: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        permit_type: str | None = None,
    ) -> list[PermitRecord]:
        """Search for permits in the jurisdiction's database.

        This is a base implementation. Subclass for specific jurisdictions.
        """
        logger.info(
            f"Permit search for {self.jurisdiction}: "
            f"address={address}, date_from={date_from}"
        )
        # Each jurisdiction has a different API/format.
        # Subclasses implement the actual scraping logic.
        return []

    async def close(self) -> None:
        await self._client.aclose()


class LIHTCScraper:
    """Scraper for state LIHTC allocation data from HFA annual reports."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=60.0)

    async def get_state_allocations(
        self,
        state: str,
        year: int | None = None,
    ) -> list[LIHTCProject]:
        """Fetch LIHTC allocation data for a state.

        In production, this scrapes state HFA websites or uses the
        HUD LIHTC database API.
        """
        logger.info(f"LIHTC lookup for state={state}, year={year}")
        # The HUD LIHTC database provides national data.
        # State HFAs publish annual allocation lists.
        # This is a placeholder for the actual scraping/API logic.
        return []

    async def close(self) -> None:
        await self._client.aclose()
