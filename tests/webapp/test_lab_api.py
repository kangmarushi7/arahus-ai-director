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


def test_admin_page_served() -> None:
    res = client.get("/admin")
    assert res.status_code == 200
    assert "Pipeline Admin" in res.text


def test_admin_runs_list_empty_or_shaped(tmp_path, monkeypatch) -> None:
    from src.audit import store as audit_store

    monkeypatch.setattr(audit_store, "_DEFAULT_DIR", tmp_path / "runs")
    res = client.get("/api/admin/runs")
    assert res.status_code == 200
    body = res.json()
    assert "runs" in body
    assert body["count"] == 0


def test_admin_run_detail_and_export(tmp_path, monkeypatch) -> None:
    from src.audit import store as audit_store

    monkeypatch.setattr(audit_store, "_DEFAULT_DIR", tmp_path / "runs")
    with audit_store.audit_run("Admin topic", run_id="22222222-2222-2222-2222-222222222222") as run:
        audit_store.record_llm_exchange(
            tag="director",
            request="plan scenes",
            response='{"scenes": []}',
            model="m",
            provider="p",
        )
        run.finish(status="completed")
        audit_store.save_run(run)

    detail = client.get("/api/admin/runs/22222222-2222-2222-2222-222222222222")
    assert detail.status_code == 200
    assert detail.json()["topic"] == "Admin topic"
    assert detail.json()["steps"][0]["tag"] == "director"

    export = client.get("/api/admin/runs/22222222-2222-2222-2222-222222222222/export")
    assert export.status_code == 200
    assert "attachment" in export.headers.get("content-disposition", "")

    csv_res = client.get("/api/admin/export.csv")
    assert csv_res.status_code == 200
    assert "run_id,topic" in csv_res.text


def test_admin_task_models_endpoints(tmp_path, monkeypatch) -> None:
    from src.llm import model_overrides as overrides
    from src.llm.openrouter_models import OpenRouterModel
    from src.webapp import model_admin as model_admin_api

    monkeypatch.setattr(overrides, "_DEFAULT_PATH", tmp_path / "overrides.json")

    fake = [
        OpenRouterModel(
            id="openai/gpt-4o-mini",
            name="GPT-4o mini",
            context_length=128000,
            input_per_million=0.15,
            output_per_million=0.6,
            is_free=False,
        )
    ]
    monkeypatch.setattr(
        model_admin_api,
        "list_openrouter_models",
        lambda **kwargs: fake,
    )
    monkeypatch.setattr(
        model_admin_api,
        "get_openrouter_model",
        lambda model_id: OpenRouterModel(
            id=model_id,
            name=model_id,
            context_length=128000,
            input_per_million=0.15,
            output_per_million=0.6,
            is_free=False,
        ),
    )

    listed = client.get("/api/admin/models")
    assert listed.status_code == 200
    assert listed.json()["models"][0]["id"] == "openai/gpt-4o-mini"

    updated = client.put(
        "/api/admin/task-models",
        json={"models": {"research": "openai/gpt-4o-mini"}},
    )
    assert updated.status_code == 200
    research = next(t for t in updated.json()["tasks"] if t["task"] == "research")
    assert research["effective_model"] == "openai/gpt-4o-mini"
    assert research["source"] == "admin"
    assert research["pricing"]["est_cost_sample"] is not None
