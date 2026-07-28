"""Per-request pipeline audit logs for admin review and export."""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

_current_run: ContextVar[PipelineRunLog | None] = ContextVar(
    "pipeline_audit_run",
    default=None,
)

_DEFAULT_DIR = Path("artifacts") / "pipeline_runs"
_lock = threading.RLock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(value: datetime | None = None) -> str:
    return (value or _utc_now()).isoformat()


@dataclass
class PipelineStepLog:
    """One tagged step inside a pipeline run (LLM, image, video, stage)."""

    tag: str
    kind: str
    created_at: str = field(default_factory=_utc_iso)
    request: str | None = None
    response: str | None = None
    model: str | None = None
    provider: str | None = None
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None
    success: bool = True
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineRunLog:
    """Full audit record for one pipeline request."""

    id: str
    topic: str
    status: str = "running"
    started_at: str = field(default_factory=_utc_iso)
    finished_at: str | None = None
    error: str | None = None
    steps: list[PipelineStepLog] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def add_step(self, step: PipelineStepLog) -> None:
        with self._lock:
            self.steps.append(step)

    def finish(
        self,
        *,
        status: str = "completed",
        error: str | None = None,
        summary: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self.status = status
            self.error = error
            self.finished_at = _utc_iso()
            if summary:
                self.summary.update(summary)

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "id": self.id,
                "topic": self.topic,
                "status": self.status,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "error": self.error,
                "steps": [step.to_dict() for step in self.steps],
                "summary": dict(self.summary),
                "step_count": len(self.steps),
                "llm_steps": sum(1 for s in self.steps if s.kind == "llm"),
                "image_steps": sum(1 for s in self.steps if s.kind == "image"),
                "video_steps": sum(1 for s in self.steps if s.kind == "video"),
            }


def get_current_run() -> PipelineRunLog | None:
    """Return the audit run bound to this context, if any."""
    return _current_run.get()


def bind_run(run: PipelineRunLog) -> Token[PipelineRunLog | None]:
    """Bind ``run`` as the current audit context."""
    return _current_run.set(run)


def reset_run(token: Token[PipelineRunLog | None]) -> None:
    """Restore the previous audit context."""
    _current_run.reset(token)


@contextmanager
def audit_run(topic: str, *, run_id: str | None = None) -> Iterator[PipelineRunLog]:
    """Start, bind, persist, and finish a pipeline audit run."""
    run = PipelineRunLog(id=run_id or str(uuid.uuid4()), topic=topic)
    token = bind_run(run)
    save_run(run)
    try:
        yield run
    except Exception as exc:
        run.finish(status="failed", error=f"{type(exc).__name__}: {exc}")
        save_run(run)
        _maybe_sync_db(run.to_dict())
        raise
    finally:
        reset_run(token)


def _maybe_sync_db(payload: dict[str, Any]) -> None:
    """Best-effort DB upsert (used on failed runs; success syncs from pipeline)."""
    try:
        from src.audit.db import sync_run_payload
        from src.config import get_settings

        settings = get_settings()
        db_url = settings.database.url.get_secret_value().strip()
        if not settings.pipeline.persist_pipeline_runs or not db_url:
            return
        sync_run_payload(payload)
    except Exception:  # noqa: BLE001 - audit DB sync is best-effort
        pass


def record_llm_exchange(
    *,
    tag: str,
    request: str,
    response: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    latency_ms: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    estimated_cost: float | None = None,
    success: bool = True,
    error: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Append an LLM request/response pair to the bound run (no-op if unbound)."""
    run = get_current_run()
    if run is None:
        return
    run.add_step(
        PipelineStepLog(
            tag=(tag or "general").strip().lower(),
            kind="llm",
            request=request,
            response=response,
            model=model,
            provider=provider,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=estimated_cost,
            success=success,
            error=error,
            meta=dict(meta or {}),
        )
    )
    save_run(run)


def record_stage_event(tag: str, message: str, *, meta: dict[str, Any] | None = None) -> None:
    """Record a non-LLM stage marker."""
    run = get_current_run()
    if run is None:
        return
    run.add_step(
        PipelineStepLog(
            tag=tag.strip().lower(),
            kind="stage",
            request=message,
            meta=dict(meta or {}),
        )
    )
    save_run(run)


def record_image_result(
    *,
    scene_id: int,
    title: str,
    prompt: str,
    url: str | None,
    status: str,
) -> None:
    """Record one generated (or failed) image."""
    run = get_current_run()
    if run is None:
        return
    run.add_step(
        PipelineStepLog(
            tag="images",
            kind="image",
            request=prompt,
            response=url,
            success=bool(url) and not status.lower().startswith("fail"),
            error=None if url else status,
            meta={"scene_id": scene_id, "title": title, "status": status, "url": url},
        )
    )
    save_run(run)


def record_video_result(
    *,
    status: str = "not_generated",
    url: str | None = None,
    note: str | None = None,
) -> None:
    """Record video output (placeholder until video pipeline ships)."""
    run = get_current_run()
    if run is None:
        return
    run.add_step(
        PipelineStepLog(
            tag="video",
            kind="video",
            request=note or "Video generation is not enabled yet.",
            response=url,
            success=bool(url),
            meta={"status": status, "url": url},
        )
    )
    save_run(run)


def runs_dir() -> Path:
    """Directory for persisted run JSON files."""
    path = _DEFAULT_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_run(run: PipelineRunLog) -> Path:
    """Write/overwrite the run JSON and refresh the index."""
    payload = run.to_dict()
    path = runs_dir() / f"{run.id}.json"
    with _lock:
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _append_index(payload)
    return path


def _append_index(payload: dict[str, Any]) -> None:
    """Upsert a compact row into index.jsonl for list views."""
    index_path = runs_dir() / "index.jsonl"
    row = {
        "id": payload["id"],
        "topic": payload["topic"],
        "status": payload["status"],
        "started_at": payload["started_at"],
        "finished_at": payload.get("finished_at"),
        "step_count": payload.get("step_count", 0),
        "llm_steps": payload.get("llm_steps", 0),
        "image_steps": payload.get("image_steps", 0),
        "error": payload.get("error"),
    }
    existing: dict[str, dict[str, Any]] = {}
    if index_path.is_file():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get("id"):
                existing[str(item["id"])] = item
    existing[str(row["id"])] = row
    ordered = sorted(
        existing.values(),
        key=lambda item: str(item.get("started_at") or ""),
        reverse=True,
    )
    index_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in ordered) + "\n",
        encoding="utf-8",
    )


def list_runs(*, limit: int = 100) -> list[dict[str, Any]]:
    """Return newest-first run summaries."""
    index_path = runs_dir() / "index.jsonl"
    if not index_path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in index_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
        if len(rows) >= max(1, limit):
            break
    return rows


def load_run(run_id: str) -> dict[str, Any] | None:
    """Load one full run by id."""
    path = runs_dir() / f"{run_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def export_runs(*, limit: int = 1000) -> list[dict[str, Any]]:
    """Load full run documents for export/analysis."""
    docs: list[dict[str, Any]] = []
    for row in list_runs(limit=limit):
        full = load_run(str(row["id"]))
        if full:
            docs.append(full)
    return docs


def messages_to_prompt_text(messages: Any) -> str:
    """Flatten chat messages into a single tagged prompt blob for logs."""
    parts: list[str] = []
    for message in messages or []:
        if isinstance(message, Mapping):
            role = str(message.get("role") or "unknown")
            content = str(message.get("content") or "")
        else:
            role = str(getattr(message, "role", "unknown"))
            content = str(getattr(message, "content", ""))
        parts.append(f"[{role}]\n{content}")
    return "\n\n".join(parts)
