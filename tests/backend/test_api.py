"""FastAPI TestClient tests for API endpoints."""

import pytest
from unittest.mock import patch, MagicMock

from main import app
from backend.auth import get_current_user_id


@pytest.fixture
def client():
    return __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app)


def _override_user(user_id: str):
    def _():
        return user_id
    return _


class TestGetSharedProject:
    """GET /api/shared/{token} - public, no auth."""

    def test_404_for_invalid_token(self, client):
        with patch("main.get_project_by_share_token", return_value=None):
            r = client.get("/api/shared/invalid-token")
        assert r.status_code == 404
        assert "no válido" in r.json().get("detail", "").lower() or "expired" in r.json().get("detail", "").lower()

    def test_200_with_valid_token(self, client):
        mock_project = {
            "id": "proj-1",
            "name": "Shared Project",
            "status": "completed",
            "segmentation": {"partes": [{"numero": 1, "titulo": "Part 1"}]},
            "partes_contenido": {"1": {"explainer": {}, "recorrido": {}, "resources": []}},
        }
        with patch("main.get_project_by_share_token", return_value=mock_project):
            r = client.get("/api/shared/valid-token-xyz")
        assert r.status_code == 200
        assert r.json()["id"] == "proj-1"
        assert r.json()["name"] == "Shared Project"


class TestCreateShare:
    """POST /api/projects/{project_id}/share - requires auth."""

    def test_401_without_auth(self, client):
        r = client.post("/api/projects/proj-1/share")
        assert r.status_code == 401

    def test_404_when_project_not_found(self, client):
        app.dependency_overrides[get_current_user_id] = _override_user("user-123")
        try:
            with patch("backend.supabase_data.get_project", return_value=None):
                with patch("main.get_project", return_value=None):
                    r = client.post(
                        "/api/projects/nonexistent/share",
                        headers={"Authorization": "Bearer fake-token"},
                    )
            assert r.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_user_id, None)

    def test_400_when_project_not_completed(self, client):
        app.dependency_overrides[get_current_user_id] = _override_user("user-123")
        try:
            with patch("main.get_project", return_value={"id": "p1", "status": "processing"}):
                with patch("main.create_share_token", return_value=None):
                    r = client.post(
                        "/api/projects/p1/share",
                        headers={"Authorization": "Bearer fake-token"},
                    )
            assert r.status_code == 400
            assert "completado" in r.json().get("detail", "").lower()
        finally:
            app.dependency_overrides.pop(get_current_user_id, None)

    def test_200_with_token(self, client):
        app.dependency_overrides[get_current_user_id] = _override_user("user-123")
        try:
            with patch("main.get_project", return_value={"id": "p1", "status": "completed"}):
                with patch("main.create_share_token", return_value="share-token-xyz"):
                    r = client.post(
                        "/api/projects/p1/share",
                        headers={"Authorization": "Bearer fake-token"},
                    )
            assert r.status_code == 200
            data = r.json()
            assert data["share_token"] == "share-token-xyz"
            assert "share_url" in data
        finally:
            app.dependency_overrides.pop(get_current_user_id, None)


class TestRevokeShare:
    """DELETE /api/projects/{project_id}/share - requires auth."""

    def test_401_without_auth(self, client):
        r = client.delete("/api/projects/proj-1/share")
        assert r.status_code == 401

    def test_404_when_project_not_found(self, client):
        app.dependency_overrides[get_current_user_id] = _override_user("user-123")
        try:
            with patch("main.get_project", return_value=None):
                r = client.delete(
                    "/api/projects/nonexistent/share",
                    headers={"Authorization": "Bearer fake-token"},
                )
            assert r.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_user_id, None)

    def test_200_on_revoke(self, client):
        app.dependency_overrides[get_current_user_id] = _override_user("user-123")
        try:
            with patch("main.get_project", return_value={"id": "p1"}):
                with patch("main.revoke_share_token"):
                    r = client.delete(
                        "/api/projects/p1/share",
                        headers={"Authorization": "Bearer fake-token"},
                    )
            assert r.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_user_id, None)


class TestGetProject:
    """GET /api/projects/{project_id} - requires auth."""

    def test_401_without_auth(self, client):
        r = client.get("/api/projects/proj-1")
        assert r.status_code == 401

    def test_404_when_project_not_found(self, client):
        app.dependency_overrides[get_current_user_id] = _override_user("user-123")
        try:
            with patch("main.get_project", return_value=None):
                r = client.get(
                    "/api/projects/nonexistent",
                    headers={"Authorization": "Bearer fake-token"},
                )
            assert r.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_user_id, None)

    def test_200_with_project(self, client):
        app.dependency_overrides[get_current_user_id] = _override_user("user-123")
        mock_project = {
            "id": "p1",
            "name": "My Project",
            "status": "completed",
            "share_token": "tok-xyz",
        }
        try:
            with patch("main.get_project", return_value=mock_project):
                r = client.get(
                    "/api/projects/p1",
                    headers={"Authorization": "Bearer fake-token"},
                )
            assert r.status_code == 200
            assert r.json()["id"] == "p1"
            assert r.json()["share_token"] == "tok-xyz"
        finally:
            app.dependency_overrides.pop(get_current_user_id, None)
