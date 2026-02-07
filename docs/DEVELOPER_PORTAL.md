# Developer Portal Guide

## Overview

The Developer Portal allows housing developers to submit and track their affordable housing projects through the HousingHand pipeline.

## Submitting a Project

### Required Information

- **Project name** - Official project name
- **Total units** - Total number of housing units
- **Location** - Address, city, state, jurisdiction

### Recommended Information

- Affordable unit count and AMI breakdown
- Building type and structure type
- Developer organization
- Site acreage and stories
- Estimated total development cost

### API Endpoint

```
POST /api/v1/projects
Content-Type: application/json

{
  "project_name": "Example Apartments",
  "address": "123 Main Street",
  "city": "Sacramento",
  "state": "CA",
  "jurisdiction": "Sacramento, CA",
  "total_units": 80,
  "affordable_units": 72,
  "building_type": "new_construction",
  "developer_org": "Example Housing Corp"
}
```

## Updating Pipeline Stage

When a project advances to the next stage:

```
PUT /api/v1/projects/{project_id}
{
  "current_stage": "entitlement",
  "stage_entry_date": "2025-06-15"
}
```

## Reporting Barriers

When a project encounters regulatory friction:

```
POST /api/v1/projects/{project_id}/barriers
{
  "barrier_type": "parking_requirements",
  "barrier_description": "Required to provide 2 spaces per unit",
  "stage_encountered": "entitlement",
  "date_encountered": "2025-03-01",
  "variance_required": true
}
```

## Data Quality

Submitted data is validated automatically. The system calculates a completeness score and flags inconsistencies. More complete data leads to better analytics and predictions.
