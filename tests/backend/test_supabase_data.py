"""Unit tests for backend supabase_data module."""

import pytest
from unittest.mock import patch, MagicMock

from backend.supabase_data import (
    _sanitize_project_for_shared,
    create_share_token,
    get_project,
    revoke_share_token,
    get_project_by_share_token,
    update_subsection_progress,
)


class TestSanitizeProjectForShared:
    """Tests for _sanitize_project_for_shared."""

    def test_strips_usage_and_reading_progress(self):
        project = {
            "id": "p1",
            "name": "Test",
            "description": "Desc",
            "status": "completed",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
            "usage": {"total_cost": 1.5, "prompt_tokens": 100},
            "reading_progress": {"completed_parts": [1, 2]},
            "segmentation": {"partes": [{"numero": 1, "titulo": "P1", "contenido": "C1"}]},
            "partes_contenido": {
                "1": {"status": "completed", "explainer": {"x": 1}, "recorrido": {}, "resources": []},
            },
        }
        out = _sanitize_project_for_shared(project)
        assert "usage" not in out
        assert "reading_progress" not in out
        assert out["id"] == "p1"
        assert out["name"] == "Test"

    def test_segmentation_only_numero_titulo_contenido(self):
        project = {
            "id": "p1",
            "name": "Test",
            "description": "",
            "status": "completed",
            "created_at": "2024-01-01",
            "updated_at": "2024-01-02",
            "segmentation": {
                "partes": [
                    {"numero": 1, "titulo": "T1", "contenido": "C1", "pagina_inicio": 1, "extra": "x"},
                ],
            },
            "partes_contenido": {},
        }
        out = _sanitize_project_for_shared(project)
        assert len(out["segmentation"]["partes"]) == 1
        p = out["segmentation"]["partes"][0]
        assert p["numero"] == 1
        assert p["titulo"] == "T1"
        assert p["contenido"] == "C1"
        assert "pagina_inicio" not in p
        assert "extra" not in p

    def test_partes_contenido_only_completed_parts(self):
        project = {
            "id": "p1",
            "name": "Test",
            "description": "",
            "status": "completed",
            "created_at": "2024-01-01",
            "updated_at": "2024-01-02",
            "segmentation": {"partes": [{"numero": 1, "titulo": "T1", "contenido": ""}]},
            "partes_contenido": {
                "1": {"status": "completed", "explainer": {"a": 1}, "recorrido": {}, "resources": []},
                "2": {"status": "pending", "explainer": None, "recorrido": None, "resources": None},
            },
        }
        out = _sanitize_project_for_shared(project)
        assert "1" in out["partes_contenido"]
        assert "2" not in out["partes_contenido"]
        assert out["partes_contenido"]["1"]["explainer"] == {"a": 1}

    def test_partes_contenido_only_explainer_recorrido_resources(self):
        project = {
            "id": "p1",
            "name": "Test",
            "description": "",
            "status": "completed",
            "created_at": "2024-01-01",
            "updated_at": "2024-01-02",
            "segmentation": {"partes": []},
            "partes_contenido": {
                "1": {
                    "status": "completed",
                    "explainer": {"x": 1},
                    "recorrido": {"y": 2},
                    "resources": [],
                    "internal_field": "secret",
                },
            },
        }
        out = _sanitize_project_for_shared(project)
        assert "internal_field" not in out["partes_contenido"]["1"]
        assert out["partes_contenido"]["1"]["explainer"] == {"x": 1}
        assert out["partes_contenido"]["1"]["recorrido"] == {"y": 2}


class TestCreateShareToken:
    """Tests for create_share_token with mocked Supabase."""

    def test_returns_none_when_project_not_found(self):
        with patch("backend.supabase_data.get_project", return_value=None):
            result = create_share_token("proj-1", "user-123")
        assert result is None

    def test_returns_none_when_project_not_completed(self):
        with patch("backend.supabase_data.get_project", return_value={"id": "p1", "status": "processing"}):
            result = create_share_token("p1", "user-123")
        assert result is None

    def test_returns_existing_token_when_already_shared(self):
        with patch("backend.supabase_data.get_project", return_value={"id": "p1", "status": "completed", "share_token": "existing-tok"}):
            result = create_share_token("p1", "user-123")
        assert result == "existing-tok"

    def test_creates_new_token(self):
        with patch("backend.supabase_data.get_project", return_value={"id": "p1", "status": "completed"}):
            with patch("backend.supabase_data.update_project", return_value=True):
                result = create_share_token("p1", "user-123")
        assert result is not None
        assert len(result) > 20


class TestRevokeShareToken:
    """Tests for revoke_share_token with mocked Supabase."""

    def test_returns_false_when_project_not_found(self):
        with patch("backend.supabase_data.get_project", return_value=None):
            result = revoke_share_token("proj-1", "user-123")
        assert result is False

    def test_returns_true_and_updates(self):
        with patch("backend.supabase_data.get_project", return_value={"id": "p1"}):
            with patch("backend.supabase_data.update_project", return_value=True):
                result = revoke_share_token("p1", "user-123")
        assert result is True


class TestGetProjectExecuteNone:
    """Regression: execute() may return None; must not access .data on None."""

    def test_returns_none_when_execute_returns_none(self):
        inner = MagicMock()
        inner.execute = MagicMock(return_value=None)
        after_second_eq = MagicMock()
        after_second_eq.maybe_single.return_value = inner
        first_eq = MagicMock()
        first_eq.eq.return_value = after_second_eq
        mock_select = MagicMock()
        mock_select.eq.return_value = first_eq
        mock_table = MagicMock()
        mock_table.select.return_value = mock_select
        with patch("backend.supabase_data._client") as mock_client:
            mock_client.return_value.table.return_value = mock_table
            result = get_project("7536ea47-abf8-4c06-8761-3a58d40e3941", "user-uuid")
        assert result is None


class TestGetProjectByShareToken:
    """Tests for get_project_by_share_token with mocked Supabase."""

    def test_returns_none_for_empty_token(self):
        result = get_project_by_share_token("")
        assert result is None
        result = get_project_by_share_token("   ")
        assert result is None

    def test_returns_none_when_not_found(self):
        mock_execute = MagicMock()
        mock_execute.data = None
        mock_maybe = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=mock_execute)))
        mock_eq = MagicMock()
        mock_eq.maybe_single = mock_maybe
        mock_select = MagicMock()
        mock_select.eq.return_value = mock_eq
        mock_table = MagicMock()
        mock_table.select.return_value = mock_select
        with patch("backend.supabase_data._client") as mock_client:
            mock_client.return_value.table.return_value = mock_table
            result = get_project_by_share_token("invalid-token")
        assert result is None


class TestApiUpdateSubsectionProgress:
    """Tests for PATCH /api/projects/{id}/progress/subsection endpoint."""

    def test_400_when_subsection_id_missing(self):
        from main import api_update_subsection_progress
        body = {"part_id": 1}
        with patch("main.get_project", return_value={"id": "p1"}):
            import asyncio
            with pytest.raises(Exception) as exc_info:
                asyncio.run(api_update_subsection_progress("user-1", "p1", body))
            assert exc_info.value.status_code == 400
            assert "subsection_id y part_id requeridos" in exc_info.value.detail

    def test_400_when_part_id_missing(self):
        from main import api_update_subsection_progress
        body = {"subsection_id": "subsec-1-0-0"}
        with patch("main.get_project", return_value={"id": "p1"}):
            import asyncio
            with pytest.raises(Exception) as exc_info:
                asyncio.run(api_update_subsection_progress("user-1", "p1", body))
            assert exc_info.value.status_code == 400
            assert "subsection_id y part_id requeridos" in exc_info.value.detail

    def test_400_when_part_id_not_a_number(self):
        from main import api_update_subsection_progress
        body = {"subsection_id": "subsec-1-0-0", "part_id": "abc"}
        with patch("main.get_project", return_value={"id": "p1"}):
            import asyncio
            with pytest.raises(Exception) as exc_info:
                asyncio.run(api_update_subsection_progress("user-1", "p1", body))
            assert exc_info.value.status_code == 400
            assert "part_id debe ser un número" in exc_info.value.detail

    def test_400_when_completed_not_bool(self):
        from main import api_update_subsection_progress
        body = {"subsection_id": "subsec-1-0-0", "part_id": 1, "completed": "yes"}
        with patch("main.get_project", return_value={"id": "p1"}):
            import asyncio
            with pytest.raises(Exception) as exc_info:
                asyncio.run(api_update_subsection_progress("user-1", "p1", body))
            assert exc_info.value.status_code == 400
            assert "completed debe ser boolean" in exc_info.value.detail

    def test_404_when_project_not_found(self):
        from main import api_update_subsection_progress
        body = {"subsection_id": "subsec-1-0-0", "part_id": 1, "completed": True}
        with patch("main.get_project", return_value=None):
            import asyncio
            with pytest.raises(Exception) as exc_info:
                asyncio.run(api_update_subsection_progress("user-1", "p1", body))
            assert exc_info.value.status_code == 404
            assert "Proyecto no encontrado" in exc_info.value.detail

    def test_400_when_part_not_found(self):
        from main import api_update_subsection_progress
        body = {"subsection_id": "subsec-1-0-0", "part_id": 1, "completed": True}
        project = {"id": "p1", "segmentation": {"partes": [{"numero": 2, "titulo": "P2"}]}}
        with patch("main.get_project", return_value=project):
            import asyncio
            with pytest.raises(Exception) as exc_info:
                asyncio.run(api_update_subsection_progress("user-1", "p1", body))
            assert exc_info.value.status_code == 400
            assert "Sección no encontrada" in exc_info.value.detail

    def test_400_when_subsection_id_does_not_belong_to_part(self):
        from main import api_update_subsection_progress
        body = {"subsection_id": "subsec-2-0-0", "part_id": 1, "completed": True}
        project = {"id": "p1", "segmentation": {"partes": [{"numero": 1, "titulo": "P1"}]}}
        with patch("main.get_project", return_value=project):
            import asyncio
            with pytest.raises(Exception) as exc_info:
                asyncio.run(api_update_subsection_progress("user-1", "p1", body))
            assert exc_info.value.status_code == 400
            assert "subsection_id no pertenece a la sección" in exc_info.value.detail

    def test_200_successful_update(self):
        from main import api_update_subsection_progress
        body = {"subsection_id": "subsec-1-0-0", "part_id": 1, "completed": True, "is_last_read": True}
        project = {"id": "p1", "segmentation": {"partes": [{"numero": 1, "titulo": "P1"}]}}
        with patch("main.get_project", return_value=project):
            with patch("main.update_subsection_progress", return_value={"reading_progress": {"completed_subsections": ["subsec-1-0-0"]}}):
                import asyncio
                result = asyncio.run(api_update_subsection_progress("user-1", "p1", body))
        assert result == {"reading_progress": {"completed_subsections": ["subsec-1-0-0"]}}

    def test_is_last_read_defaults_to_false(self):
        from main import api_update_subsection_progress
        body = {"subsection_id": "subsec-1-0-0", "part_id": 1, "completed": True}
        project = {"id": "p1", "segmentation": {"partes": [{"numero": 1, "titulo": "P1"}]}}
        with patch("main.get_project", return_value=project):
            with patch("main.update_subsection_progress", return_value={"ok": True}) as mock_update:
                import asyncio
                asyncio.run(api_update_subsection_progress("user-1", "p1", body))
        mock_update.assert_called_once_with("p1", "user-1", "subsec-1-0-0", 1, completed=True, is_last_read=False)


class TestUpdateSubsectionProgress:
    """Tests for update_subsection_progress with mocked Supabase."""

    def test_returns_none_when_project_not_found(self):
        with patch("backend.supabase_data.get_project", return_value=None):
            result = update_subsection_progress("proj-1", "user-1", "subsec-1-0-0", 1, completed=True)
        assert result is None

    def test_adds_subsection_to_completed(self):
        project = {"id": "p1", "reading_progress": {"completed_parts": [1]}}
        captured = {}

        def capture_update(pid, uid, updates):
            captured["updates"] = updates
            return {"id": "p1", "reading_progress": updates.get("reading_progress", {})}

        with patch("backend.supabase_data.get_project", return_value=project):
            with patch("backend.supabase_data.update_project", side_effect=capture_update):
                result = update_subsection_progress("p1", "user-1", "subsec-1-0-0", 1, completed=True)
        assert result is not None
        rp = result["reading_progress"]
        assert "subsec-1-0-0" in rp["completed_subsections"]
        assert rp["completed_parts"] == [1]

    def test_does_not_duplicate_completed(self):
        project = {"id": "p1", "reading_progress": {"completed_subsections": ["subsec-1-0-0"]}}
        captured = {}

        def capture_update(pid, uid, updates):
            captured["updates"] = updates
            return {"id": "p1", "reading_progress": updates.get("reading_progress", {})}

        with patch("backend.supabase_data.get_project", return_value=project):
            with patch("backend.supabase_data.update_project", side_effect=capture_update):
                result = update_subsection_progress("p1", "user-1", "subsec-1-0-0", 1, completed=True)
        assert result is not None
        rp = result["reading_progress"]
        assert rp["completed_subsections"].count("subsec-1-0-0") == 1

    def test_removes_from_completed(self):
        project = {"id": "p1", "reading_progress": {"completed_subsections": ["subsec-1-0-0", "subsec-2-0-0"]}}
        captured = {}

        def capture_update(pid, uid, updates):
            captured["updates"] = updates
            return {"id": "p1", "reading_progress": updates.get("reading_progress", {})}

        with patch("backend.supabase_data.get_project", return_value=project):
            with patch("backend.supabase_data.update_project", side_effect=capture_update):
                result = update_subsection_progress("p1", "user-1", "subsec-1-0-0", 1, completed=False)
        assert result is not None
        rp = result["reading_progress"]
        assert "subsec-1-0-0" not in rp["completed_subsections"]
        assert "subsec-2-0-0" in rp["completed_subsections"]

    def test_sets_last_subsection_when_is_last_read(self):
        project = {"id": "p1", "reading_progress": {}}
        captured = {}

        def capture_update(pid, uid, updates):
            captured["updates"] = updates
            return {"id": "p1", "reading_progress": updates.get("reading_progress", {})}

        with patch("backend.supabase_data.get_project", return_value=project):
            with patch("backend.supabase_data.update_project", side_effect=capture_update):
                result = update_subsection_progress("p1", "user-1", "subsec-1-0-0", 1, is_last_read=True)
        assert result is not None
        rp = result["reading_progress"]
        assert rp["last_subsection"]["subsection_id"] == "subsec-1-0-0"
        assert rp["last_subsection"]["part_id"] == 1
        assert rp["last_subsection"]["tab"] == "explicacion"
        assert "last_read_at" in rp

    def test_preserves_existing_progress_keys(self):
        project = {"id": "p1", "reading_progress": {"completed_parts": [1, 2], "last_read_at": "2024-01-01T00:00:00Z"}}
        captured = {}

        def capture_update(pid, uid, updates):
            captured["updates"] = updates
            return {"id": "p1", "reading_progress": updates.get("reading_progress", {})}

        with patch("backend.supabase_data.get_project", return_value=project):
            with patch("backend.supabase_data.update_project", side_effect=capture_update):
                result = update_subsection_progress("p1", "user-1", "subsec-1-0-0", 1, completed=True)
        assert result is not None
        rp = result["reading_progress"]
        assert rp["completed_parts"] == [1, 2]
        assert rp["last_read_at"] == "2024-01-01T00:00:00Z"
        assert "subsec-1-0-0" in rp["completed_subsections"]

    def test_no_last_subsection_when_not_is_last_read(self):
        project = {"id": "p1", "reading_progress": {"last_subsection": {"part_id": 2, "subsection_id": "subsec-2-0-0", "tab": "explicacion"}}}
        captured = {}

        def capture_update(pid, uid, updates):
            captured["updates"] = updates
            return {"id": "p1", "reading_progress": updates.get("reading_progress", {})}

        with patch("backend.supabase_data.get_project", return_value=project):
            with patch("backend.supabase_data.update_project", side_effect=capture_update):
                result = update_subsection_progress("p1", "user-1", "subsec-1-0-0", 1, completed=True, is_last_read=False)
        assert result is not None
        rp = result["reading_progress"]
        assert "last_read_at" not in rp
        assert rp["last_subsection"]["subsection_id"] == "subsec-2-0-0"
