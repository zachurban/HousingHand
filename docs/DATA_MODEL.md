# HousingHand Data Model

## Overview

HousingHand tracks affordable housing projects through seven pipeline stages from concept to long-term operations.

## Core Tables

### projects

The central table tracking every affordable housing project.

**Key fields:**
- `project_id` (UUID, PK) - Unique identifier
- `project_slug` (string, unique) - URL-friendly identifier
- `current_stage` - Pipeline stage enum
- `overall_health` - Health status enum
- `health_score` - Numeric health score (0-100)
- `jurisdiction` - Links to HousingLens friction data

**Timeline fields:** Each stage has `_start`, `_complete`, and `_duration_days` columns.

**Cost fields:** Total development cost, component breakdown, and friction-induced costs.

### funding_sources

Many-to-one relationship with projects. Tracks each funding source with type, amount, status, and terms.

### project_barriers

Many-to-one relationship with projects. Links specific regulatory friction points to project delays with cost and time impact.

### peer_groups

Defines comparable project cohorts for benchmarking. Stores calculated statistics (medians, percentiles).

### portfolio_dashboards

Saved portfolio configurations with cached aggregate metrics.

### policy_reforms

Tracks regulatory changes with pre/post impact measurements and statistical significance.

## Pipeline Stages

1. **Concept** - Site identified, preliminary feasibility
2. **Pre-Development** - Due diligence, community engagement
3. **Entitlement** - Zoning approvals, design review
4. **Financing** - Tax credit applications, loan underwriting
5. **Construction** - Groundbreaking to certificate of occupancy
6. **Lease-Up** - Marketing and tenant placement
7. **Operations** - Long-term affordability compliance

Additional statuses: `stalled`, `abandoned`

## Enumerations

See `src/models/enums.py` for all enum definitions including BuildingType, StructureType, FundingSourceType, OverallHealth, etc.
