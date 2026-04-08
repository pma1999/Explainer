"""GET /api/projects returns list_summary items without heavy keys."""

from unittest.mock import patch

from main import app
from backend.auth import get_current_user_id


def _client():
    return __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app)


def _override_user(user_id: str):
    def _():
        return user_id

    return _


class TestListProjectsSummary:
    def test_list_excludes_heavy_fields_and_sets_flag(self):
        client = _client()
        app.dependency_overrides[get_current_user_id] = _override_user("user-1")
        try:
            with patch(
                "main.list_projects_summary",
                return_value=[
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440000",
                        "name": "P1",
                        "description": "",
                        "pdf_filename": "a.pdf",
                        "source_type": "pdf",
                        "source_url": None,
                        "source_metadata": {},
                        "file_uri": None,
                        "status": "completed",
                        "segmentation": {"partes": [{"numero": 1}]},
                        "usage": {},
                        "reading_progress": {},
                        "error_message": None,
                        "share_token": None,
                        "created_at": "2024-01-01T12:00:00",
                        "updated_at": "2024-01-02T12:00:00",
                        "list_summary": True,
                    }
                ],
            ):
                r = client.get("/api/projects", headers={"Authorization": "Bearer fake"})
        finally:
            app.dependency_overrides.pop(get_current_user_id, None)

        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["list_summary"] is True
        assert "partes_contenido" not in data[0]
        assert "source_text" not in data[0]
