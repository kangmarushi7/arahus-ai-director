"""Persist audit runs into PostgreSQL when DATABASE_URL is configured."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from src.database.base import utc_now
from src.database.models.pipeline_run import (
    PipelineLogEntry,
    PipelineLogKind,
    PipelineRun,
    PipelineRunStatus,
)
from src.database.session import get_session

logger = logging.getLogger(__name__)


def sync_run_payload(payload: dict[str, Any]) -> None:
    """Upsert a full audit document into ``pipeline_runs`` + log entries."""
    run_id = uuid.UUID(str(payload["id"]))
    status = PipelineRunStatus(str(payload.get("status") or "running"))
    started_at = _parse_dt(payload.get("started_at"))
    finished_at = _parse_dt(payload.get("finished_at"))

    with get_session() as session:
        row = session.get(PipelineRun, run_id)
        if row is None:
            row = PipelineRun(id=run_id, topic=str(payload.get("topic") or ""))
            session.add(row)
        row.topic = str(payload.get("topic") or row.topic)
        row.status = status
        if started_at is not None:
            row.started_at = started_at
        row.finished_at = finished_at
        row.error = payload.get("error")
        row.summary_json = json.dumps(payload.get("summary") or {}, ensure_ascii=False)
        row.payload_json = json.dumps(payload, ensure_ascii=False)

        # Replace entries for a consistent snapshot.
        row.entries.clear()
        session.flush()
        for step in payload.get("steps") or []:
            if not isinstance(step, dict):
                continue
            kind_raw = str(step.get("kind") or "stage")
            try:
                kind = PipelineLogKind(kind_raw)
            except ValueError:
                kind = PipelineLogKind.STAGE
            entry = PipelineLogEntry(
                run_id=run_id,
                tag=str(step.get("tag") or "general")[:64],
                kind=kind,
                created_at=_parse_dt(step.get("created_at")) or utc_now(),
                request=step.get("request"),
                response=step.get("response"),
                model=(str(step["model"])[:256] if step.get("model") else None),
                provider=(str(step["provider"])[:64] if step.get("provider") else None),
                latency_ms=_as_float(step.get("latency_ms")),
                input_tokens=_as_int(step.get("input_tokens")),
                output_tokens=_as_int(step.get("output_tokens")),
                estimated_cost=_as_float(step.get("estimated_cost")),
                success=bool(step.get("success", True)),
                error=step.get("error"),
                meta_json=json.dumps(step.get("meta") or {}, ensure_ascii=False),
            )
            session.add(entry)
    logger.info(
        "event=audit_db_synced run_id=%s status=%s steps=%s",
        run_id,
        status.value,
        len(payload.get("steps") or []),
    )


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
