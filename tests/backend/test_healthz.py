"""Public healthcheck endpoint tests (A1)."""

from __future__ import annotations


class TestHealthz:
    """GET /healthz must respond immediately without auth or Supabase."""

    def test_healthz_returns_ok_without_token(self, client):
        r = client.get("/healthz")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["status"] == "healthy"

    def test_healthz_works_even_with_invalid_auth_header(self, client):
        # Even a bogus Authorization header must not break the public probe.
        r = client.get("/healthz", headers={"Authorization": "Bearer garbage"})
        assert r.status_code == 200
        assert r.json()["ok"] is True
