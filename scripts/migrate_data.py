#!/usr/bin/env python3
"""Data migration utilities for importing projects from external sources."""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import logging

from src.data_collection.developer_portal import DeveloperPortalService
from src.data_collection.validation import DataValidator
from src.database.connection import get_session_factory

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def import_from_csv(csv_path: str) -> dict:
    """Import project data from a CSV file.

    Expected columns: project_name, address, city, state, jurisdiction,
    developer_org, total_units, affordable_units, building_type, current_stage
    """
    SessionLocal = get_session_factory()
    db = SessionLocal()
    service = DeveloperPortalService(db)
    validator = DataValidator()

    results = {"imported": 0, "skipped": 0, "errors": 0}

    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    # Clean up the row data
                    data = {k.strip(): v.strip() for k, v in row.items() if v and v.strip()}

                    # Convert numeric fields
                    for field in ["total_units", "affordable_units"]:
                        if field in data:
                            data[field] = int(data[field])

                    project = service.create_project(data)
                    validation = validator.validate_project(project)

                    if not validation.is_valid:
                        logger.warning(
                            f"Project '{data.get('project_name')}' has validation errors: "
                            f"{validation.errors}"
                        )

                    results["imported"] += 1

                except Exception as e:
                    logger.error(f"Error importing row: {e}")
                    results["errors"] += 1

        logger.info(f"Import complete: {results}")
        return results

    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python migrate_data.py <csv_path>")
        sys.exit(1)
    import_from_csv(sys.argv[1])
