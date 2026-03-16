"""FastAPI TestClient tests for API endpoints."""

import pytest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from main import app
from backend.auth import get_current_user_id
from backend.url_extraction import WebExtractionError


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


class TestCreateProject:
    """POST /api/projects - supports PDF, YouTube and web URLs."""

    def test_401_without_auth(self, client):
        r = client.post("/api/projects", data={"name": "Test", "web_url": "https://example.com"})
        assert r.status_code == 401

    def test_creates_web_project_with_normalized_url(self, auth_client):
        mock_project = {"id": "web-1", "source_type": "web", "source_url": "https://example.com/article"}
        with patch("main._normalize_web_source_url", return_value="https://example.com/article"):
            with patch("main.supabase_create_project", return_value=mock_project) as mock_create:
                r = auth_client.post(
                    "/api/projects",
                    headers={"Authorization": "Bearer fake-token"},
                    data={
                        "name": "Artículo",
                        "description": "Texto completo",
                        "web_url": "https://example.com/article#intro",
                    },
                )

        assert r.status_code == 200
        assert r.json()["source_type"] == "web"
        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        assert kwargs["source_type"] == "web"
        assert kwargs["source_url"] == "https://example.com/article"
        assert kwargs["pdf_content"] is None

    def test_rejects_invalid_web_url(self, auth_client):
        with patch("main._normalize_web_source_url", side_effect=WebExtractionError("URL web inválida")):
            r = auth_client.post(
                "/api/projects",
                headers={"Authorization": "Bearer fake-token"},
                data={"name": "Artículo", "web_url": "nota-url"},
            )

        assert r.status_code == 400
        assert r.json()["detail"] == "URL web inválida"

    def test_rejects_multiple_sources(self, auth_client):
        r = auth_client.post(
            "/api/projects",
            headers={"Authorization": "Bearer fake-token"},
            data={
                "name": "Proyecto mixto",
                "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "web_url": "https://example.com/article",
            },
        )

        assert r.status_code == 400
        assert "solo una fuente" in r.json()["detail"].lower()

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


class TestReformatProjectMarkdown:
    """POST /api/projects/{project_id}/reformat-markdown - retrofit markdown formatting."""

    def test_404_when_project_not_found(self, auth_client):
        with patch("main.get_project", return_value=None):
            r = auth_client.post("/api/projects/missing/reformat-markdown", headers={"Authorization": "Bearer fake-token"})
        assert r.status_code == 404

    def test_400_when_no_api_key(self, auth_client):
        mock_project = {"id": "p1", "partes_contenido": {"1": {"explainer": {"desarrollo": []}}}}
        with patch("main.get_project", return_value=mock_project):
            with patch("main.has_user_api_key", return_value=False):
                r = auth_client.post("/api/projects/p1/reformat-markdown", headers={"Authorization": "Bearer fake-token"})
        assert r.status_code == 400

    def test_200_reformats_explainer_content(self, auth_client):
        base_project = {
            "id": "p1",
            "usage": {"total_tokens": 100, "total_cost": 0.02},
            "partes_contenido": {
                "1": {"explainer": {"desarrollo": [{"subsecciones": [{"explicacion_detallada": "A"}]}]}},
                "2": {"explainer": {"error": "fail"}},
            },
        }

        def _fake_reformat(_api_key, payload):
            payload["desarrollo"][0]["subsecciones"][0]["explicacion_detallada"] = "- A"
            usage = SimpleNamespace(
                prompt_token_count=3,
                candidates_token_count=2,
                thoughts_token_count=1,
                total_token_count=6,
            )
            return payload, usage

        with patch("main.get_project", return_value=base_project):
            with patch("main.has_user_api_key", return_value=True):
                with patch("main.get_user_api_key", return_value="AIzaFakeKey"):
                    with patch("main.reformat_explainer_payload_markdown", side_effect=_fake_reformat):
                        with patch("main.update_project", side_effect=lambda _p, _u, updates: {**base_project, **updates}):
                            r = auth_client.post("/api/projects/p1/reformat-markdown", headers={"Authorization": "Bearer fake-token"})

        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["formatted_parts"] == 1
        assert body["project"]["partes_contenido"]["1"]["explainer"]["desarrollo"][0]["subsecciones"][0]["explicacion_detallada"] == "- A"
        assert body["project"]["usage"]["total_tokens"] == 106
        assert body["project"]["usage"]["total_cost"] == pytest.approx(0.020005, abs=1e-9)
