# HousingHand

Development Pipeline Intelligence Platform for the HousingMind ecosystem.

HousingHand tracks every affordable housing project from concept to certificate of occupancy, quantifying where development pipelines break down and connecting regulatory friction to real production outcomes. It creates the first comprehensive affordable housing development pipeline database, enabling stakeholders to predict timelines, identify bottlenecks, measure policy reform impact, and optimize portfolio performance.

## Core Capabilities

- **Pipeline Tracking** - Monitor affordable housing projects through all seven development stages
- **Health Assessment** - Weighted scoring system evaluating timeline, budget, funding, risk, and team stability
- **Bottleneck Intelligence** - Identify systematic barriers that delay or kill projects across jurisdictions
- **Predictive Analytics** - Forecast project timelines using ML models trained on historical data and jurisdiction friction scores
- **Policy Impact Measurement** - Quantify actual outcomes of regulatory reforms with statistical significance testing
- **Portfolio Intelligence** - Aggregate views for PHAs, funders, cities, and policymakers

## Tech Stack

- **API**: Python 3.10+, FastAPI
- **Database**: PostgreSQL 14+ with PostGIS
- **ML/Analytics**: scikit-learn, pandas, numpy, scipy
- **Task Queue**: Celery + Redis
- **Testing**: pytest

## Quick Start

```bash
# Clone and set up
cp .env.example .env

# Docker
cd docker && docker compose up -d

# Or local development
python -m venv venv && source venv/bin/activate
pip install -r requirements/dev.txt
pip install -r requirements/ml.txt
uvicorn src.api.app:app --reload
```

## Project Structure

```
src/
  api/           # FastAPI application and endpoints
  models/        # SQLAlchemy models (Project, FundingSource, Barrier, etc.)
  analytics/     # Core analytics engine
  ml/            # Timeline prediction ML model
  integrations/  # HousingLens, HousingEar, HousingMind clients
  data_collection/  # Developer portal, permit scrapers
  database/      # Connection, queries, migrations
  tasks/         # Celery async tasks
  utils/         # Helper utilities
tests/           # Test suite
config/          # Settings and YAML configuration
scripts/         # Database seeding, model training, reports
docker/          # Docker and compose files
docs/            # Documentation
```

## HousingMind Ecosystem Integration

- **HousingLens** - Regulatory friction scores predict entitlement timelines
- **HousingEar** - Policy monitoring feeds reform impact measurement
- **HousingMind** - Query metadata tracks stakeholder engagement patterns

## Documentation

- [API Reference](docs/API.md)
- [Data Model](docs/DATA_MODEL.md)
- [Analytics Methodology](docs/ANALYTICS.md)
- [Integration Guide](docs/INTEGRATION_GUIDE.md)
- [Developer Portal](docs/DEVELOPER_PORTAL.md)
- [Deployment Guide](docs/DEPLOYMENT.md)

## License

©️ 2026 Zachary Urban 
All Rights Reserved
