# HousingHand Deployment Guide

## Prerequisites

- Docker and Docker Compose
- PostgreSQL 14+ with PostGIS extension
- Redis 7+
- Python 3.10+ (for local development)

## Quick Start (Docker)

```bash
# Copy environment config
cp .env.example .env

# Start all services
cd docker
docker compose up -d

# Run migrations
docker compose exec api alembic upgrade head

# Seed sample data
docker compose exec api python scripts/seed_database.py
```

## Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements/dev.txt
pip install -r requirements/ml.txt

# Set up environment
cp .env.example .env
# Edit .env with your local database credentials

# Run migrations
alembic upgrade head

# Start API server
uvicorn src.api.app:app --reload --port 8000

# Start Celery worker (separate terminal)
celery -A src.tasks.celery_app worker --loglevel=info

# Start Celery beat (separate terminal)
celery -A src.tasks.celery_app beat --loglevel=info
```

## Running Tests

```bash
# Local
pytest tests/ -v --cov=src

# Docker
cd docker
docker compose -f docker-compose.test.yml up --abort-on-container-exit
```

## Database Migrations

```bash
# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

## Environment Variables

See `.env.example` for all available configuration options.

## Production Considerations

- Set `API_DEBUG=false`
- Use a strong `API_SECRET_KEY`
- Configure proper database credentials
- Set up SSL/TLS termination
- Configure log aggregation
- Set up monitoring and alerting
- Schedule regular database backups
