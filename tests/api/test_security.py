"""API security — auth middleware, CORS policy, path sanitization."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.config import reload_settings
from src.security import parse_cors_origins
from src.security.paths import safe_path_segment


def test_safe_path_segment_blocks_traversal() -> None:
    assert ".." not in safe_path_segment("../etc/passwd")
    assert "/" not in safe_path_segment("a/b")
    assert "\\" not in safe_path_segment("a\\b")
    assert safe_path_segment("") == "unknown"


def test_parse_cors_origins_defaults_and_star() -> None:
    assert "http://localhost:3000" in parse_cors_origins("")
    assert parse_cors_origins("*") == ["*"]
    assert parse_cors_origins("https://a.com, https://b.com") == [
        "https://a.com",
        "https://b.com",
    ]


def test_api_key_required_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARAHUS_API_KEY", "secret-test-key")
    monkeypatch.setenv("ALLOW_STUB_SERVICES", "true")
    reload_settings()
    app = create_app(enable_cors=False)
    client = TestClient(app)

    denied = client.get("/projects")
    assert denied.status_code == 401

    ok_health = client.get("/health")
    assert ok_health.status_code == 200

    authorized = client.get(
        "/projects",
        headers={"Authorization": "Bearer secret-test-key"},
    )
    assert authorized.status_code != 401

    reload_settings()


def test_api_open_when_key_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARAHUS_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("ALLOW_STUB_SERVICES", "true")
    reload_settings()
    app = create_app(enable_cors=False)
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    # Unauthenticated projects list should not be 401 when key unset
    response = client.get("/projects")
    assert response.status_code != 401
    reload_settings()
