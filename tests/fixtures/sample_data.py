"""Sample data dictionaries for HousingHand tests.

These are raw data dicts (not ORM objects) that can be used to construct
test payloads, compare against API responses, and seed test databases
via the factory fixtures in ``conftest.py``.
"""

from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Sample project data dicts
# ---------------------------------------------------------------------------

SAMPLE_PROJECT_MINIMAL = {
    "project_name": "Minimal Test Project",
    "total_units": 50,
}

SAMPLE_PROJECT_CREATE_PAYLOAD = {
    "project_name": "Sunrise Village Apartments",
    "city": "Oakland",
    "state": "CA",
    "jurisdiction": "City of Oakland",
    "total_units": 120,
    "affordable_units": 108,
    "market_units": 12,
    "building_type": "new_construction",
    "structure_type": "wood_frame",
    "stories": 4,
    "current_stage": "entitlement",
    "developer_org": "Community Housing Partners",
    "total_development_cost": 42_000_000.00,
    "is_public": True,
}

SAMPLE_PROJECT_FULL = {
    "project_name": "Harbor View Family Housing",
    "city": "San Francisco",
    "county": "San Francisco",
    "state": "CA",
    "zip": "94107",
    "jurisdiction": "City and County of San Francisco",
    "neighborhood": "Mission Bay",
    "latitude": 37.7749,
    "longitude": -122.4194,
    "developer_org": "Tenderloin Neighborhood Development Corp",
    "architect": "Leddy Maytum Stacy Architects",
    "general_contractor": "Cahill Contractors",
    "property_manager": "John Stewart Company",
    "site_acres": 1.8,
    "building_type": "new_construction",
    "structure_type": "concrete",
    "stories": 8,
    "parking_spaces": 40,
    "total_units": 200,
    "affordable_units": 200,
    "market_units": 0,
    "studio_units": 20,
    "one_br_units": 60,
    "two_br_units": 80,
    "three_br_units": 30,
    "four_plus_br_units": 10,
    "ami_30_units": 40,
    "ami_40_units": 20,
    "ami_50_units": 60,
    "ami_60_units": 60,
    "ami_80_units": 20,
    "senior_units": 0,
    "family_units": 200,
    "homeless_set_aside": 20,
    "current_stage": "financing",
    "total_development_cost": 95_000_000.00,
    "cost_per_unit": 475_000.00,
    "land_acquisition_cost": 15_000_000.00,
    "hard_costs": 60_000_000.00,
    "soft_costs": 12_000_000.00,
    "is_public": True,
    "data_source": "developer_portal",
}

SAMPLE_PROJECT_UPDATE_PAYLOAD = {
    "current_stage": "financing",
    "total_development_cost": 43_500_000.00,
    "entitlement_complete": str(date.today()),
}


# ---------------------------------------------------------------------------
# Multiple project scenarios for analytics tests
# ---------------------------------------------------------------------------

def make_on_track_project_data() -> dict:
    """Project that is healthy: on schedule, under budget, team complete."""
    return {
        "project_name": "Greenfield Heights On-Track",
        "city": "Oakland",
        "state": "CA",
        "jurisdiction": "City of Oakland",
        "total_units": 80,
        "affordable_units": 72,
        "market_units": 8,
        "building_type": "new_construction",
        "structure_type": "wood_frame",
        "stories": 3,
        "current_stage": "entitlement",
        "days_in_current_stage": 60,
        "stage_entry_date": str(date.today() - timedelta(days=60)),
        "developer_org": "Oakland Community Builders",
        "architect": "Modern Arc Studio",
        "general_contractor": "Bay Builders Inc",
        "property_manager": "Westside Management",
        "total_development_cost": 28_000_000.00,
        "original_budget": 28_000_000.00,
        "current_budget": 27_500_000.00,
        "budget_variance_percent": -1.8,
        "risk_score": 15.0,
        "jurisdiction_friction_score": 30,
        "health_score": 85.0,
        "overall_health": "on_track",
        "data_completeness": 0.95,
    }


def make_at_risk_project_data() -> dict:
    """Project with emerging risks: behind schedule, moderate opposition."""
    return {
        "project_name": "Eastside Commons At-Risk",
        "city": "Oakland",
        "state": "CA",
        "jurisdiction": "City of Oakland",
        "total_units": 60,
        "affordable_units": 54,
        "market_units": 6,
        "building_type": "substantial_rehab",
        "structure_type": "mixed",
        "stories": 3,
        "current_stage": "entitlement",
        "days_in_current_stage": 350,
        "stage_entry_date": str(date.today() - timedelta(days=350)),
        "developer_org": "East Bay Housing Corp",
        "total_development_cost": 22_000_000.00,
        "original_budget": 20_000_000.00,
        "current_budget": 22_000_000.00,
        "budget_variance_percent": 10.0,
        "risk_score": 55.0,
        "jurisdiction_friction_score": 60,
        "neighbor_opposition_level": "moderate",
        "health_score": 55.0,
        "overall_health": "at_risk",
    }


def make_delayed_project_data() -> dict:
    """Significantly delayed project: over budget, legal challenges."""
    return {
        "project_name": "West End Towers Delayed",
        "city": "Berkeley",
        "state": "CA",
        "jurisdiction": "City of Berkeley",
        "total_units": 150,
        "affordable_units": 135,
        "market_units": 15,
        "building_type": "new_construction",
        "structure_type": "concrete",
        "stories": 6,
        "current_stage": "entitlement",
        "days_in_current_stage": 500,
        "stage_entry_date": str(date.today() - timedelta(days=500)),
        "developer_org": "Regional Housing Alliance",
        "total_development_cost": 65_000_000.00,
        "original_budget": 50_000_000.00,
        "current_budget": 65_000_000.00,
        "budget_variance_percent": 30.0,
        "risk_score": 75.0,
        "jurisdiction_friction_score": 80,
        "neighbor_opposition_level": "high",
        "appeals_filed": 2,
        "health_score": 35.0,
        "overall_health": "delayed",
    }


def make_stalled_project_data() -> dict:
    """Completely stalled project: severe problems across all dimensions."""
    return {
        "project_name": "Riverside Place Stalled",
        "city": "San Jose",
        "state": "CA",
        "jurisdiction": "City of San Jose",
        "total_units": 90,
        "affordable_units": 81,
        "market_units": 9,
        "building_type": "adaptive_reuse",
        "structure_type": "steel",
        "stories": 5,
        "current_stage": "stalled",
        "days_in_current_stage": 400,
        "stage_entry_date": str(date.today() - timedelta(days=400)),
        "total_development_cost": 40_000_000.00,
        "original_budget": 30_000_000.00,
        "current_budget": 40_000_000.00,
        "budget_variance_percent": 33.3,
        "risk_score": 92.0,
        "jurisdiction_friction_score": 90,
        "neighbor_opposition_level": "severe",
        "appeals_filed": 3,
        "health_score": 12.0,
        "overall_health": "stalled",
    }


# ---------------------------------------------------------------------------
# Sample funding source data
# ---------------------------------------------------------------------------

SAMPLE_FUNDING_SOURCES = [
    {
        "source_type": "LIHTC_4pct",
        "source_name": "California LIHTC 4%",
        "provider_organization": "CTCAC",
        "amount": 15_000_000.00,
        "status": "committed",
    },
    {
        "source_type": "HOME",
        "source_name": "HOME Investment Partnership",
        "provider_organization": "HUD",
        "amount": 3_000_000.00,
        "status": "awarded",
    },
    {
        "source_type": "construction_loan",
        "source_name": "Wells Fargo Construction Loan",
        "provider_organization": "Wells Fargo Bank",
        "amount": 20_000_000.00,
        "status": "anticipated",
    },
    {
        "source_type": "local_trust_fund",
        "source_name": "Oakland Housing Trust Fund",
        "provider_organization": "City of Oakland",
        "amount": 2_500_000.00,
        "status": "applied",
    },
]


# ---------------------------------------------------------------------------
# Sample barrier data
# ---------------------------------------------------------------------------

SAMPLE_BARRIERS = [
    {
        "barrier_type": "Minimum Parking Requirements",
        "barrier_description": "City requires 1.5 spaces/unit; project designed for 0.5.",
        "jurisdiction": "City of Oakland",
        "friction_score": 65,
        "stage_encountered": "entitlement",
        "days_delayed": 45,
        "cost_impact": 250_000.00,
        "variance_required": True,
    },
    {
        "barrier_type": "Height Limit Restriction",
        "barrier_description": "Zoning caps height at 35 feet; project needs 55 feet.",
        "jurisdiction": "City of Oakland",
        "friction_score": 70,
        "stage_encountered": "entitlement",
        "days_delayed": 90,
        "cost_impact": 500_000.00,
        "variance_required": True,
    },
    {
        "barrier_type": "Environmental Review (CEQA)",
        "barrier_description": "Full EIR required due to neighbor objection.",
        "jurisdiction": "City of Berkeley",
        "friction_score": 80,
        "stage_encountered": "pre_development",
        "days_delayed": 180,
        "cost_impact": 750_000.00,
        "variance_required": False,
    },
    {
        "barrier_type": "Design Review Iterations",
        "barrier_description": "Planning commission required 4 rounds of design changes.",
        "jurisdiction": "City of San Francisco",
        "friction_score": 55,
        "stage_encountered": "entitlement",
        "days_delayed": 120,
        "cost_impact": 350_000.00,
        "variance_required": False,
    },
]


# ---------------------------------------------------------------------------
# Sample reform data
# ---------------------------------------------------------------------------

SAMPLE_REFORM = {
    "jurisdiction": "City of Oakland",
    "reform_name": "Parking Minimum Elimination",
    "reform_description": "Eliminated minimum parking requirements for projects within 0.5mi of transit.",
    "reform_type": "parking_reform",
    "effective_date": str(date(2023, 7, 1)),
    "projects_pre_reform": 15,
    "projects_post_reform": 8,
    "pre_reform_median_days": 300,
    "post_reform_median_days": 210,
    "days_saved_per_project": 90,
    "percent_improvement": 30.0,
    "total_cost_savings": 3_600_000.00,
    "units_enabled": 200,
}


# ---------------------------------------------------------------------------
# HousingLens mock API responses
# ---------------------------------------------------------------------------

HOUSING_LENS_JURISDICTION_RESPONSE = {
    "overall_score": 62,
    "topics": [
        {
            "name": "parking_minimums",
            "friction_score": 75,
            "jurisdiction_rank": 8,
            "national_percentile": 82.0,
            "description": "Minimum parking requirements above transit-oriented thresholds.",
        },
        {
            "name": "height_limits",
            "friction_score": 60,
            "jurisdiction_rank": 15,
            "national_percentile": 68.0,
            "description": "Restrictive height limits in high-opportunity zones.",
        },
        {
            "name": "density_caps",
            "friction_score": 45,
            "jurisdiction_rank": 22,
            "national_percentile": 55.0,
            "description": "Per-acre unit caps below state density bonus allowances.",
        },
    ],
    "last_updated": "2024-06-15T00:00:00",
}

HOUSING_LENS_RELATED_TOPICS_RESPONSE = {
    "topics": [
        {
            "name": "parking_minimums",
            "friction_score": 75,
            "jurisdiction_rank": 8,
        },
    ],
}
