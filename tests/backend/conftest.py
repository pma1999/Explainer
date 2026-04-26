"""Pytest fixtures for backend API tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.auth import get_current_user_id


@pytest.fixture
def client():
    """FastAPI TestClient."""
    from main import app
    return TestClient(app)


@pytest.fixture
def auth_client(client, override_get_current_user):
    """Client with auth dependency overridden to return a user_id."""
    app = client.app
    app.dependency_overrides[get_current_user_id] = override_get_current_user
    yield client
    app.dependency_overrides.pop(get_current_user_id, None)


@pytest.fixture
def override_get_current_user():
    """Default override: returns user-123."""
    def _override():
        return "user-123"
    return _override
