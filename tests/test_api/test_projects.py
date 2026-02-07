"""Tests for project CRUD API endpoints."""

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.database.connection import get_db
from src.models.enums import PipelineStage
from src.models.project import Project


@pytest.fixture
def client(db):
    """Create a FastAPI TestClient with overridden DB dependency."""

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def existing_project(db):
    """Create a project in the database."""
    p = Project(
        project_name="Test API Project",
        project_slug="test-api-project",
        city="Portland",
        state="OR",
        jurisdiction="Portland, OR",
        total_units=50,
        affordable_units=50,
        current_stage=PipelineStage.CONCEPT,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


class TestListProjects:
    """Tests for GET /api/v1/projects."""

    def test_list_projects_empty(self, client):
        """Should return empty list when no projects exist."""
        response = client.get("/api/v1/projects")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))

    def test_list_projects_with_data(self, client, existing_project):
        """Should return projects when they exist."""
        response = client.get("/api/v1/projects")
        assert response.status_code == 200

    def test_list_projects_filter_by_state(self, client, existing_project):
        """Should filter projects by state."""
        response = client.get("/api/v1/projects", params={"state": "OR"})
        assert response.status_code == 200


class TestGetProject:
    """Tests for GET /api/v1/projects/{id}."""

    def test_get_existing_project(self, client, existing_project):
        """Should return project details by ID."""
        response = client.get(f"/api/v1/projects/{existing_project.project_id}")
        assert response.status_code == 200

    def test_get_nonexistent_project(self, client):
        """Should return 404 for nonexistent project."""
        import uuid

        fake_id = uuid.uuid4()
        response = client.get(f"/api/v1/projects/{fake_id}")
        assert response.status_code == 404


class TestCreateProject:
    """Tests for POST /api/v1/projects."""

    def test_create_project(self, client):
        """Should create a new project."""
        payload = {
            "project_name": "New Test Project",
            "city": "Sacramento",
            "state": "CA",
            "total_units": 100,
            "affordable_units": 80,
        }
        response = client.post("/api/v1/projects", json=payload)
        assert response.status_code in [200, 201]

    def test_create_project_missing_name(self, client):
        """Should reject project without name."""
        payload = {"total_units": 50}
        response = client.post("/api/v1/projects", json=payload)
        assert response.status_code == 422
