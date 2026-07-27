"""Smoke tests for the FastAPI lab."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.webapp.main import app


client = TestClient(app)


def test_health() -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_index_served() -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "Arahus" in res.text


def test_status_shape() -> None:
    res = client.get("/api/status")
    assert res.status_code == 200
    body = res.json()
    for key in ("llm", "runpod", "r2", "database", "allow_stubs", "ready"):
        assert key in body
