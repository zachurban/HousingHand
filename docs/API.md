# HousingHand API Documentation

## Base URL

```
http://localhost:8000/api/v1
```

## Authentication

API key authentication via `Authorization: Bearer <key>` header.

## Endpoints

### Projects

| Method | Path | Description |
|--------|------|-------------|
| GET | `/projects` | List projects with filtering |
| POST | `/projects` | Create a new project |
| GET | `/projects/{id}` | Get project details |
| PUT | `/projects/{id}` | Update a project |
| DELETE | `/projects/{id}` | Delete a project |

#### Query Parameters (GET /projects)

- `jurisdiction` - Filter by jurisdiction
- `city` - Filter by city
- `state` - Filter by state (2-letter code)
- `current_stage` - Filter by pipeline stage
- `overall_health` - Filter by health status
- `limit` - Results per page (default: 50, max: 200)
- `offset` - Pagination offset

### Health Assessments

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health/{project_id}` | Get health assessment |
| POST | `/health/batch` | Batch health assessment |

### Analytics

| Method | Path | Description |
|--------|------|-------------|
| GET | `/analytics/bottlenecks` | Jurisdiction bottleneck analysis |

#### Query Parameters

- `jurisdiction` (required)
- `timeframe` - Analysis window (default: `last_24_months`)

### Predictions

| Method | Path | Description |
|--------|------|-------------|
| POST | `/predictions/timeline` | Predict project timeline |

### Portfolio

| Method | Path | Description |
|--------|------|-------------|
| POST | `/portfolio/intelligence` | Generate portfolio dashboard |

### Reforms

| Method | Path | Description |
|--------|------|-------------|
| POST | `/reforms` | Create policy reform record |
| GET | `/reforms/{id}/impact` | Measure reform impact |

## Response Format

All responses follow this structure:

```json
{
  "data": { ... },
  "meta": {
    "total": 100,
    "limit": 50,
    "offset": 0
  }
}
```

Error responses:

```json
{
  "detail": "Error message"
}
```

## Status Codes

- `200` - Success
- `201` - Created
- `400` - Bad request
- `404` - Not found
- `422` - Validation error
- `500` - Internal server error
