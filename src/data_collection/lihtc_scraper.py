"""Scraper for state LIHTC annual reports and HUD LIHTC database."""

import logging

from src.integrations.public_records import LIHTCProject, LIHTCScraper

logger = logging.getLogger(__name__)

# HUD LIHTC database endpoint
HUD_LIHTC_BASE_URL = "https://lihtc.huduser.gov/api"


class HUDLIHTCScraper(LIHTCScraper):
    """Scraper for the HUD national LIHTC database."""

    async def get_state_allocations(
        self,
        state: str,
        year: int | None = None,
    ) -> list[LIHTCProject]:
        """Fetch LIHTC allocation data from the HUD database."""
        params: dict = {"state": state.upper()}
        if year:
            params["yr_alloc"] = year

        try:
            response = await self._client.get(
                f"{HUD_LIHTC_BASE_URL}/projects",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            return [
                LIHTCProject(
                    project_name=r.get("project", ""),
                    address=r.get("project_st", ""),
                    city=r.get("proj_cty", ""),
                    state=r.get("proj_st", state),
                    credit_type=r.get("type", ""),
                    total_units=int(r.get("n_units", 0) or 0),
                    low_income_units=int(r.get("li_units", 0) or 0),
                    allocation_year=int(r.get("yr_alloc", 0) or 0),
                    placed_in_service_date=r.get("yr_pis", ""),
                    total_credit=float(r.get("allocamt", 0) or 0),
                )
                for r in data.get("results", [])
            ]
        except Exception:
            logger.exception(f"Error fetching LIHTC data for {state}")
            return []

    async def search_by_city(
        self,
        city: str,
        state: str,
    ) -> list[LIHTCProject]:
        """Search LIHTC projects in a specific city."""
        all_projects = await self.get_state_allocations(state)
        return [
            p for p in all_projects
            if p.city.lower() == city.lower()
        ]
