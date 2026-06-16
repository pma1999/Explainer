"""FastAPI TestClient tests for API endpoints."""

import pytest
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


class TestProcessProject:
    """POST /api/projects/{project_id}/process - provider selection is explicit per execution."""

    def test_defaults_to_gemini_when_body_is_missing(self, auth_client):
        scheduled: dict = {}

        async def _fake_process(
            project_id,
            user_id,
            explainer_provider="gemini",
            openrouter_model=None,
            deepseek_model=None,
            target_language="es-ES",
        ):
            scheduled.update({
                "project_id": project_id,
                "user_id": user_id,
                "explainer_provider": explainer_provider,
                "openrouter_model": openrouter_model,
                "deepseek_model": deepseek_model,
                "target_language": target_language,
            })

        with patch(
            "main.get_project",
            return_value={"id": "proj-1", "name": "Proyecto", "status": "pending", "source_type": "pdf"},
        ):
            with patch("main.has_user_api_key", side_effect=lambda uid, provider="google_gemini": True):
                with patch("main._process_project", new=_fake_process):
                    r = auth_client.post(
                        "/api/projects/proj-1/process",
                        headers={"Authorization": "Bearer fake-token"},
                    )

        assert r.status_code == 200
        assert r.json()["explainer_provider"] == "gemini"
        assert r.json()["explainer_model"] == "gemini-3.1-flash-lite-preview"
        assert scheduled["explainer_provider"] == "gemini"
        assert scheduled["openrouter_model"] is None
        assert scheduled["deepseek_model"] is None
        assert scheduled["target_language"] == "es-ES"

    def test_requires_openrouter_key_when_openrouter_is_selected(self, auth_client):
        with patch(
            "main.get_project",
            return_value={"id": "proj-1", "name": "Proyecto", "status": "pending", "source_type": "pdf"},
        ):
            with patch(
                "main.has_user_api_key",
                side_effect=lambda uid, provider="google_gemini": provider != "openrouter",
            ):
                r = auth_client.post(
                    "/api/projects/proj-1/process",
                    headers={"Authorization": "Bearer fake-token"},
                    json={"explainer_provider": "openrouter"},
                )

        assert r.status_code == 400
        assert "OpenRouter" in r.json()["detail"]

    def test_youtube_with_openrouter_falls_back_to_gemini_automatically(self, auth_client):
        scheduled: dict = {}

        async def _fake_process(
            project_id,
            user_id,
            explainer_provider="gemini",
            openrouter_model=None,
            deepseek_model=None,
            target_language="es-ES",
        ):
            scheduled.update({"project_id": project_id, "explainer_provider": explainer_provider})

        with patch(
            "main.get_project",
            return_value={"id": "yt-1", "name": "Vídeo", "status": "pending", "source_type": "youtube"},
        ):
            with patch("main.has_user_api_key", side_effect=lambda uid, provider="google_gemini": True):
                with patch("main._process_project", new=_fake_process):
                    r = auth_client.post(
                        "/api/projects/yt-1/process",
                        headers={"Authorization": "Bearer fake-token"},
                        json={"explainer_provider": "openrouter"},
                    )

        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_accepts_supported_openrouter_model_selection(self, auth_client):
        scheduled: dict = {}

        async def _fake_process(
            project_id,
            user_id,
            explainer_provider="gemini",
            openrouter_model=None,
            deepseek_model=None,
            target_language="es-ES",
        ):
            scheduled.update({
                "project_id": project_id,
                "user_id": user_id,
                "explainer_provider": explainer_provider,
                "openrouter_model": openrouter_model,
                "deepseek_model": deepseek_model,
                "target_language": target_language,
            })

        with patch(
            "main.get_project",
            return_value={"id": "proj-1", "name": "Proyecto", "status": "pending", "source_type": "pdf"},
        ):
            with patch("main.has_user_api_key", side_effect=lambda uid, provider="google_gemini": True):
                with patch("main._process_project", new=_fake_process):
                    r = auth_client.post(
                        "/api/projects/proj-1/process",
                        headers={"Authorization": "Bearer fake-token"},
                        json={
                            "explainer_provider": "openrouter",
                            "openrouter_model": "xiaomi/mimo-v2.5",
                        },
                    )

        assert r.status_code == 200
        assert r.json()["explainer_provider"] == "openrouter"
        assert r.json()["explainer_model"] == "xiaomi/mimo-v2.5"
        assert scheduled["explainer_provider"] == "openrouter"
        assert scheduled["openrouter_model"] == "xiaomi/mimo-v2.5"
        assert scheduled["deepseek_model"] is None
        assert scheduled["target_language"] == "es-ES"

    def test_rejects_unsupported_openrouter_model_selection(self, auth_client):
        with patch(
            "main.get_project",
            return_value={"id": "proj-1", "name": "Proyecto", "status": "pending", "source_type": "pdf"},
        ):
            r = auth_client.post(
                "/api/projects/proj-1/process",
                headers={"Authorization": "Bearer fake-token"},
                json={
                    "explainer_provider": "openrouter",
                    "openrouter_model": "qwen/qwen3.6-plus",
                },
            )

        assert r.status_code == 422

    def test_accepts_deepseek_direct_for_web_without_gemini_key(self, auth_client):
        scheduled: dict = {}

        async def _fake_process(
            project_id,
            user_id,
            explainer_provider="gemini",
            openrouter_model=None,
            deepseek_model=None,
            target_language="es-ES",
        ):
            scheduled.update({
                "project_id": project_id,
                "user_id": user_id,
                "explainer_provider": explainer_provider,
                "openrouter_model": openrouter_model,
                "deepseek_model": deepseek_model,
                "target_language": target_language,
            })

        def _has_key(uid, provider="google_gemini"):
            return provider in {"deepseek", "tavily"}

        with patch(
            "main.get_project",
            return_value={"id": "proj-web", "name": "Proyecto", "status": "pending", "source_type": "web"},
        ):
            with patch("main.has_user_api_key", side_effect=_has_key):
                with patch("main._process_project", new=_fake_process):
                    r = auth_client.post(
                        "/api/projects/proj-web/process",
                        headers={"Authorization": "Bearer fake-token"},
                        json={
                            "explainer_provider": "deepseek",
                            "deepseek_model": "deepseek-v4-flash",
                        },
                    )

        assert r.status_code == 200
        assert r.json()["explainer_provider"] == "deepseek"
        assert r.json()["explainer_model"] == "deepseek-v4-flash"
        assert scheduled["explainer_provider"] == "deepseek"
        assert scheduled["openrouter_model"] is None
        assert scheduled["deepseek_model"] == "deepseek-v4-flash"

    def test_requires_tavily_key_when_deepseek_direct_is_selected(self, auth_client):
        def _has_key(uid, provider="google_gemini"):
            return provider == "deepseek"

        with patch(
            "main.get_project",
            return_value={"id": "proj-web", "name": "Proyecto", "status": "pending", "source_type": "web"},
        ):
            with patch("main.has_user_api_key", side_effect=_has_key):
                r = auth_client.post(
                    "/api/projects/proj-web/process",
                    headers={"Authorization": "Bearer fake-token"},
                    json={"explainer_provider": "deepseek"},
                )

        assert r.status_code == 400
        assert "Tavily" in r.json()["detail"]

    def test_requires_mistral_key_when_deepseek_direct_is_selected_for_pdf(self, auth_client):
        def _has_key(uid, provider="google_gemini"):
            return provider in {"deepseek", "tavily"}

        with patch(
            "main.get_project",
            return_value={"id": "proj-pdf", "name": "Proyecto", "status": "pending", "source_type": "pdf"},
        ):
            with patch("main.has_user_api_key", side_effect=_has_key):
                r = auth_client.post(
                    "/api/projects/proj-pdf/process",
                    headers={"Authorization": "Bearer fake-token"},
                    json={"explainer_provider": "deepseek"},
                )

        assert r.status_code == 400
        assert "Mistral" in r.json()["detail"]


class TestMistralApiKeys:
    def test_status_exposes_mistral_fields(self, auth_client):
        with patch(
            "main.get_user_api_key_status",
            return_value={
                "has_api_key": True,
                "provider": "google_gemini",
                "updated_at": "2026-04-13T10:00:00Z",
                "has_openrouter_key": True,
                "openrouter_updated_at": "2026-04-13T10:00:00Z",
                "has_mistral_key": True,
                "mistral_updated_at": "2026-04-13T10:00:00Z",
                "has_deepseek_key": True,
                "deepseek_updated_at": "2026-04-13T10:00:00Z",
                "has_tavily_key": True,
                "tavily_updated_at": "2026-04-13T10:00:00Z",
            },
        ):
            response = auth_client.get(
                "/api/settings/api-key/status",
                headers={"Authorization": "Bearer fake-token"},
            )

        assert response.status_code == 200
        assert response.json()["has_mistral_key"] is True
        assert response.json()["mistral_updated_at"] == "2026-04-13T10:00:00Z"
        assert response.json()["has_deepseek_key"] is True
        assert response.json()["has_tavily_key"] is True

    def test_requires_mistral_key_when_openrouter_is_selected_for_pdf(self, auth_client):
        with patch(
            "main.get_project",
            return_value={"id": "proj-1", "name": "Proyecto", "status": "pending", "source_type": "pdf"},
        ):
            with patch(
                "main.has_user_api_key",
                side_effect=lambda uid, provider="google_gemini": provider != "mistral",
            ):
                response = auth_client.post(
                    "/api/projects/proj-1/process",
                    headers={"Authorization": "Bearer fake-token"},
                    json={"explainer_provider": "openrouter"},
                )

        assert response.status_code == 400
        assert "Mistral" in response.json()["detail"]

    def test_does_not_require_mistral_key_for_openrouter_web_projects(self, auth_client):
        with patch(
            "main.get_project",
            return_value={"id": "proj-web", "name": "Proyecto", "status": "pending", "source_type": "web"},
        ):
            with patch(
                "main.has_user_api_key",
                side_effect=lambda uid, provider="google_gemini": provider != "mistral",
            ):
                async def _fake_process(*args, **kwargs):
                    return None

                with patch("main._process_project", new=_fake_process):
                    response = auth_client.post(
                        "/api/projects/proj-web/process",
                        headers={"Authorization": "Bearer fake-token"},
                        json={"explainer_provider": "openrouter"},
                    )

        assert response.status_code == 200
