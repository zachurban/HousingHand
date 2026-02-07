"""Geography and jurisdiction utilities."""

import re

# Mapping of state abbreviations to regions for peer comparison
STATE_REGIONS: dict[str, str] = {
    "CT": "northeast", "ME": "northeast", "MA": "northeast", "NH": "northeast",
    "RI": "northeast", "VT": "northeast", "NJ": "northeast", "NY": "northeast",
    "PA": "northeast",
    "IL": "midwest", "IN": "midwest", "MI": "midwest", "OH": "midwest",
    "WI": "midwest", "IA": "midwest", "KS": "midwest", "MN": "midwest",
    "MO": "midwest", "NE": "midwest", "ND": "midwest", "SD": "midwest",
    "DE": "south", "FL": "south", "GA": "south", "MD": "south",
    "NC": "south", "SC": "south", "VA": "south", "DC": "south",
    "WV": "south", "AL": "south", "KY": "south", "MS": "south",
    "TN": "south", "AR": "south", "LA": "south", "OK": "south", "TX": "south",
    "AZ": "west", "CO": "west", "ID": "west", "MT": "west",
    "NV": "west", "NM": "west", "UT": "west", "WY": "west",
    "AK": "west", "CA": "west", "HI": "west", "OR": "west", "WA": "west",
}

# Population tiers for jurisdiction comparison
POPULATION_TIERS = {
    "small": (0, 50_000),
    "medium": (50_000, 250_000),
    "large": (250_000, 1_000_000),
    "major": (1_000_000, float("inf")),
}


def normalize_jurisdiction(name: str) -> str:
    """Normalize a jurisdiction name for consistent matching.

    Strips whitespace, lowercases, removes common suffixes like 'City of'.
    """
    name = name.strip().lower()
    # Remove common prefixes
    for prefix in ["city of ", "town of ", "village of ", "county of "]:
        if name.startswith(prefix):
            name = name[len(prefix):]
    # Remove trailing state abbreviation patterns like ", CA"
    name = re.sub(r",\s*[a-z]{2}$", "", name)
    return name.strip()


def get_region(state: str) -> str | None:
    """Return the census region for a state abbreviation."""
    return STATE_REGIONS.get(state.upper())


def find_comparable_jurisdictions(
    jurisdiction: str,
    state: str | None = None,
    max_results: int = 5,
) -> list[str]:
    """Find comparable jurisdictions for benchmarking.

    In production this would query the database for jurisdictions with similar:
    - Population size
    - Regional location
    - Housing market characteristics

    This is a placeholder that returns an empty list until real data is available.
    """
    # In production, this queries the database for jurisdictions with similar
    # population, region, and housing market characteristics.
    # For now, return empty - the caller handles the case of no peers.
    return []


def is_same_metro(jurisdiction_a: str, jurisdiction_b: str) -> bool:
    """Check if two jurisdictions are in the same metropolitan area.

    Placeholder for MSA/CBSA lookup integration.
    """
    return normalize_jurisdiction(jurisdiction_a) == normalize_jurisdiction(jurisdiction_b)
