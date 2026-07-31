"""SSE endpoint token delivery tests (A4): Authorization header first, query param fallback."""

from __future__ import annotations

import contextlib
from contextlib import ExitStack

import pytest
from unittest.mock import patch

from main import app


@pytest.fixture
def client():
    return __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app)


_MISSING = object()


class TestProjectEventsAuth:
    """GET /api/projects/{project_id}/events — token from header or query param."""

    @contextlib.contextmanager
    def _patched_auth_and_project(self, token_user_map=None, project=_MISSING):
        """Patch token verification, project lookup and the SSE stream.

        token_user_map: dict token -> user_id (get_user_id_from_token mock).
        project: value returned by get_project; pass None to simulate not-found.
        """
        if token_user_map is None:
            token_user_map = {"valid-token": "user-123"}
        if project is _MISSING:
            project = {"id": "proj-1", "status": "processing"}

        class _DummySSE:
            async def subscribe_events(self, project_id):
                yield {"type": "stream_end"}

        with ExitStack() as stack:
            stack.enter_context(
                patch("main.get_user_id_from_token", side_effect=lambda t: token_user_map.get(t))
            )
            stack.enter_context(patch("main.get_project", return_value=project))
            stack.enter_context(patch("main.sse_manager", new=_DummySSE()))
            yield

    def test_200_with_bearer_header(self, client):
        with self._patched_auth_and_project():
            r = client.get(
                "/api/projects/proj-1/events",
                headers={"Authorization": "Bearer valid-token"},
            )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")

    def test_200_with_query_token_fallback(self, client):
        with self._patched_auth_and_project():
            r = client.get("/api/projects/proj-1/events", params={"token": "valid-token"})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")

    def test_header_takes_precedence_over_query(self, client):
        with self._patched_auth_and_project({"header-token": "user-123", "query-token": "user-999"}):
            r = client.get(
                "/api/projects/proj-1/events",
                params={"token": "query-token"},
                headers={"Authorization": "Bearer header-token"},
            )
        assert r.status_code == 200

    def test_401_when_both_missing(self, client):
        with self._patched_auth_and_project():
            r = client.get("/api/projects/proj-1/events")
        assert r.status_code == 401

    def test_401_when_token_invalid(self, client):
        with self._patched_auth_and_project():
            r = client.get(
                "/api/projects/proj-1/events",
                headers={"Authorization": "Bearer invalid-token"},
            )
        assert r.status_code == 401

    def test_404_when_project_not_found(self, client):
        with self._patched_auth_and_project(project=None):
            r = client.get(
                "/api/projects/proj-1/events",
                headers={"Authorization": "Bearer valid-token"},
            )
        assert r.status_code == 404
