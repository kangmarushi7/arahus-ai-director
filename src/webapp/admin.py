"""Admin API for pipeline request audit logs and model selection."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from src.audit.store import export_runs, list_runs, load_run
from src.webapp.model_admin import (
    apply_task_model_updates,
    models_catalog_payload,
    task_models_payload,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class TaskModelsUpdate(BaseModel):
    """Body for updating per-task model overrides."""

    models: dict[str, str | None] = Field(
        default_factory=dict,
        description="Map of task name → OpenRouter model id (null/empty clears).",
    )


@router.get("/runs")
def admin_list_runs(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    """List recent pipeline request summaries (newest first)."""
    rows = list_runs(limit=limit)
    return {"runs": rows, "count": len(rows)}


@router.get("/runs/{run_id}")
def admin_get_run(run_id: str) -> dict[str, Any]:
    """Return the full audit document for one request id."""
    payload = load_run(run_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    return payload


@router.get("/runs/{run_id}/export")
def admin_export_run_json(run_id: str) -> Response:
    """Download one run as JSON."""
    payload = load_run(run_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="pipeline-run-{run_id}.json"'
        },
    )


@router.get("/export.json")
def admin_export_all_json(limit: int = Query(default=500, ge=1, le=5000)) -> Response:
    """Download many full runs as a JSON array for analysis."""
    docs = export_runs(limit=limit)
    body = json.dumps(docs, indent=2, ensure_ascii=False)
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="pipeline-runs-export.json"'
        },
    )


@router.get("/export.csv")
def admin_export_csv(limit: int = Query(default=500, ge=1, le=5000)) -> StreamingResponse:
    """Download a flat CSV of every logged step across runs."""
    docs = export_runs(limit=limit)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "run_id",
            "topic",
            "run_status",
            "run_started_at",
            "run_finished_at",
            "tag",
            "kind",
            "created_at",
            "model",
            "provider",
            "latency_ms",
            "input_tokens",
            "output_tokens",
            "estimated_cost",
            "success",
            "error",
            "request",
            "response",
        ],
        extrasaction="ignore",
    )
    writer.writeheader()
    for doc in docs:
        for step in doc.get("steps") or []:
            writer.writerow(
                {
                    "run_id": doc.get("id"),
                    "topic": doc.get("topic"),
                    "run_status": doc.get("status"),
                    "run_started_at": doc.get("started_at"),
                    "run_finished_at": doc.get("finished_at"),
                    "tag": step.get("tag"),
                    "kind": step.get("kind"),
                    "created_at": step.get("created_at"),
                    "model": step.get("model"),
                    "provider": step.get("provider"),
                    "latency_ms": step.get("latency_ms"),
                    "input_tokens": step.get("input_tokens"),
                    "output_tokens": step.get("output_tokens"),
                    "estimated_cost": step.get("estimated_cost"),
                    "success": step.get("success"),
                    "error": step.get("error"),
                    "request": step.get("request"),
                    "response": step.get("response"),
                }
            )
    data = buffer.getvalue().encode("utf-8")
    return StreamingResponse(
        iter([data]),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="pipeline-runs-export.csv"'
        },
    )


@router.get("/models")
def admin_list_models(
    q: str | None = Query(default=None, description="Filter by id/name"),
    refresh: bool = Query(default=False),
    limit: int = Query(default=400, ge=1, le=2000),
) -> dict[str, Any]:
    """List OpenRouter models with USD-per-million pricing."""
    try:
        return models_catalog_payload(query=q, force_refresh=refresh, limit=limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/task-models")
def admin_get_task_models() -> dict[str, Any]:
    """Return effective models per pipeline task with cost estimates."""
    try:
        return task_models_payload()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/task-models")
def admin_put_task_models(body: TaskModelsUpdate) -> dict[str, Any]:
    """Set admin overrides for research/director/prompt/review/domain models."""
    try:
        return apply_task_model_updates(body.models)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
