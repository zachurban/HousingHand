#!/usr/bin/env python3
"""Generate ad-hoc reports from HousingHand data."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import logging

from src.analytics.bottleneck_detection import identify_systemic_bottlenecks
from src.analytics.portfolio_intelligence import generate_portfolio_intelligence
from src.database.connection import get_session_factory

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def portfolio_report(jurisdiction: str) -> None:
    """Generate a portfolio intelligence report for a jurisdiction."""
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        result = generate_portfolio_intelligence(
            db=db,
            geography_filter={"jurisdiction": jurisdiction},
            stakeholder_type="city",
        )
        print(json.dumps(result, indent=2, default=str))
    finally:
        db.close()


def bottleneck_report(jurisdiction: str, timeframe: str = "last_24_months") -> None:
    """Generate a bottleneck analysis report for a jurisdiction."""
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        result = identify_systemic_bottlenecks(
            db=db,
            jurisdiction=jurisdiction,
            timeframe=timeframe,
        )
        print(json.dumps(result, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python generate_reports.py <report_type> <jurisdiction>")
        print("Report types: portfolio, bottleneck")
        sys.exit(1)

    report_type = sys.argv[1]
    jurisdiction = sys.argv[2]

    if report_type == "portfolio":
        portfolio_report(jurisdiction)
    elif report_type == "bottleneck":
        timeframe = sys.argv[3] if len(sys.argv) > 3 else "last_24_months"
        bottleneck_report(jurisdiction, timeframe)
    else:
        print(f"Unknown report type: {report_type}")
        sys.exit(1)
