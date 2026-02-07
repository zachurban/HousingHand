# HousingHand Integration Guide

## HousingMind Ecosystem

HousingHand integrates with three other HousingMind components:

### HousingLens (Friction Scores)

HousingLens provides jurisdiction-level regulatory friction scores that HousingHand uses for:
- Predicting project timelines
- Identifying bottleneck root causes
- Validating observed delays against predicted friction

**Configuration:**
```
HOUSING_LENS_API_URL=http://housing-lens-api:8001/api/v1
HOUSING_LENS_API_KEY=your-api-key
```

**Client:** `src/integrations/housing_lens.py`

### HousingEar (Policy Monitoring)

HousingEar monitors policy changes and funding opportunities. HousingHand uses this to:
- Alert projects about new funding programs
- Track policy reforms for impact measurement
- Connect regulatory changes to pipeline outcomes

**Configuration:**
```
HOUSING_EAR_API_URL=http://housing-ear-api:8002/api/v1
HOUSING_EAR_API_KEY=your-api-key
```

**Client:** `src/integrations/housing_ear.py`

### HousingMind (Query Metadata)

HousingMind sends webhook events when users query about specific projects or jurisdictions. HousingHand tracks these to understand stakeholder engagement patterns.

**Configuration:**
```
HOUSING_MIND_WEBHOOK_SECRET=your-webhook-secret
```

**Webhook endpoint:** `POST /api/v1/webhooks/housing-mind`

## Data Sources

### Developer Portal
Developers submit and update project data through the API.

### Public Records
Permit databases and LIHTC allocation data are scraped periodically.

### Funder Reports
Funding organizations can submit portfolio data via API or batch import.
