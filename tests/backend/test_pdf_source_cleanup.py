from __future__ import annotations

from copy import deepcopy
from unittest.mock import MagicMock, patch

import main
import pytest
from fastapi import BackgroundTasks, HTTPException

from backend.supabase_data import (
    SOURCE_OBJECT_STATUS_DELETED,
    SOURCE_OBJECT_STATUS_STORED,
    create_project,
    delete_project_source_object,
    download_pdf_to_temp,
)


def _build_mock_projects_table() -> MagicMock:
    table = MagicMock()
    table.insert.return_value.execute.return_value = None
    table.update.return_value.eq.return_value.eq.return_value.execute.return_value = None
    table.delete.return_value.eq.return_value.eq.return_value.execute.return_value = None
    return table


def test_create_project_rolls_back_project_row_when_pdf_upload_fails():
    mock_bucket = MagicMock()
    mock_bucket.upload.side_effect = RuntimeError("upload failed")
    mock_bucket.remove.return_value = None

    mock_client = MagicMock()
    mock_client.storage.from_.return_value = mock_bucket
    mock_client.table.return_value = _build_mock_projects_table()

    with (
        patch("backend.supabase_data._client", return_value=mock_client),
        patch("backend.supabase_data.uuid.uuid4", return_value="proj-1"),
        patch("backend.supabase_data._now_iso", return_value="2026-05-19T12:00:00Z"),
    ):
        try:
            create_project(
                user_id="user-1",
                name="Proyecto",
                description="Desc",
                pdf_filename="documento.pdf",
                pdf_content=b"%PDF-test",
                source_type="pdf",
            )
            raise AssertionError("create_project debería haber propagado el fallo de upload")
        except RuntimeError as exc:
            assert str(exc) == "upload failed"

    mock_bucket.remove.assert_called_once_with(["user-1/proj-1/documento.pdf"])
    mock_client.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute.assert_called_once()


def test_delete_project_source_object_marks_row_deleted_when_storage_object_is_missing():
    mock_bucket = MagicMock()
    mock_bucket.remove.side_effect = RuntimeError("404 object not found")

    mock_client = MagicMock()
    mock_client.storage.from_.return_value = mock_bucket
    mock_client.table.return_value = _build_mock_projects_table()

    project = {
        "id": "proj-1",
        "user_id": "user-1",
        "pdf_filename": "documento.pdf",
        "source_type": "pdf",
        "source_object_path": "user-1/proj-1/documento.pdf",
        "source_object_status": SOURCE_OBJECT_STATUS_STORED,
    }

    with patch("backend.supabase_data._client", return_value=mock_client):
        deleted = delete_project_source_object("proj-1", "user-1", project=project)

    assert deleted is True
    update_payload = mock_client.table.return_value.update.call_args.args[0]
    assert update_payload["source_object_status"] == SOURCE_OBJECT_STATUS_DELETED
    assert update_payload["source_object_deleted_at"]


def test_download_pdf_to_temp_returns_none_for_deleted_source_without_hitting_storage():
    project = {
        "id": "proj-1",
        "user_id": "user-1",
        "pdf_filename": "documento.pdf",
        "source_type": "pdf",
        "source_object_status": SOURCE_OBJECT_STATUS_DELETED,
    }

    with (
        patch("backend.supabase_data.get_project", return_value=project),
        patch("backend.supabase_data._client") as mock_client,
    ):
        assert download_pdf_to_temp("proj-1", "user-1") is None
        mock_client.assert_not_called()


def test_reconcile_stored_pdf_sources_marks_active_projects_as_error_and_cleans_them(monkeypatch):
    projects = [
        {
            "id": "proj-1",
            "user_id": "user-1",
            "status": "processing",
            "source_type": "pdf",
            "source_object_status": SOURCE_OBJECT_STATUS_STORED,
            "source_object_path": "user-1/proj-1/documento.pdf",
        }
    ]
    updates = []
    cleaned = []

    monkeypatch.setattr(main, "list_projects_with_stored_source_objects", lambda: projects)
    monkeypatch.setattr(
        main,
        "update_project",
        lambda pid, uid, payload: updates.append((pid, uid, deepcopy(payload))),
    )
    monkeypatch.setattr(
        main,
        "delete_project_source_object",
        lambda pid, uid, project=None: cleaned.append((pid, uid, deepcopy(project))) or True,
    )

    main._reconcile_stored_pdf_sources_on_startup()

    assert updates == [
        (
            "proj-1",
            "user-1",
            {
                "status": "error",
                "error_message": main.INTERRUPTED_PDF_PROCESS_ERROR_MESSAGE,
            },
        )
    ]
    assert cleaned == [("proj-1", "user-1", projects[0])]


def test_reconcile_stored_pdf_sources_leaves_pending_projects_untouched(monkeypatch):
    projects = [
        {
            "id": "proj-1",
            "user_id": "user-1",
            "status": "pending",
            "source_type": "pdf",
            "source_object_status": SOURCE_OBJECT_STATUS_STORED,
            "source_object_path": "user-1/proj-1/documento.pdf",
        }
    ]
    cleaned = []

    monkeypatch.setattr(main, "list_projects_with_stored_source_objects", lambda: projects)
    monkeypatch.setattr(
        main,
        "update_project",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("pending no debe tocarse")),
    )
    monkeypatch.setattr(
        main,
        "delete_project_source_object",
        lambda *args, **kwargs: cleaned.append(True),
    )

    main._reconcile_stored_pdf_sources_on_startup()

    assert cleaned == []


def test_api_process_project_rejects_pdf_without_stored_source(monkeypatch):
    project = {
        "id": "proj-1",
        "name": "Proyecto",
        "status": "error",
        "source_type": "pdf",
        "source_object_status": SOURCE_OBJECT_STATUS_DELETED,
    }

    monkeypatch.setattr(main, "get_project", lambda pid, uid, include_internal=False: project)
    monkeypatch.setattr(main, "has_user_api_key", lambda uid, provider=None: True)

    with pytest.raises(HTTPException) as exc_info:
        import asyncio

        asyncio.run(
            main.api_process_project(
                user_id="user-1",
                project_id="proj-1",
                background_tasks=BackgroundTasks(),
                payload=None,
            )
        )

    assert exc_info.value.status_code == 400
    assert main.MISSING_PDF_SOURCE_ERROR_MESSAGE in exc_info.value.detail
