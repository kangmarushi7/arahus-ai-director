"""FastAPI web lab for end-to-end Arahus pipeline testing."""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.config import reload_settings
from src.pipeline import PipelineValidationError
from src.progress import ProgressUpdate
from src.webapp.serialize import config_status_payload, serialize_result

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = REPO_ROOT / "web"

app = FastAPI(
    title="Arahus Lab",
    description="Simple end-to-end pipeline test console",
    version="1.0.0",
)

if (WEB_ROOT / "static").is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_ROOT / "static")), name="static")


class RunRequest(BaseModel):
    """Body for starting a pipeline run."""

    topic: str = Field(min_length=1, max_length=512)


@app.get("/health")
def health() -> dict[str, str]:
    """Railway / load-balancer health probe."""
    return {"status": "ok"}


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    """Integration readiness for the sidebar."""
    return config_status_payload()


@app.get("/")
def index() -> FileResponse:
    """Serve the lab UI."""
    index_path = WEB_ROOT / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=404, detail="web/index.html missing")
    return FileResponse(index_path)


@app.post("/api/run")
async def run_pipeline(body: RunRequest) -> StreamingResponse:
    """Run the pipeline and stream progress events (NDJSON over SSE)."""
    topic = " ".join(body.topic.split())
    if not topic:
        raise HTTPException(status_code=400, detail="topic must be non-empty")

    status = config_status_payload()
    if not status["llm"]:
        raise HTTPException(
            status_code=503,
            detail="OPENROUTER_API_KEY is not configured",
        )
    if not status["ready"]:
        raise HTTPException(
            status_code=503,
            detail=(
                "RunPod/R2 are not configured. Set credentials or "
                "ALLOW_STUB_SERVICES=true for dry runs."
            ),
        )

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_progress(update: ProgressUpdate) -> None:
        payload = {
            "type": "progress",
            "message": update.message,
            "fraction": update.fraction,
            "stages": dict(update.stages),
            "stage_panel": update.stage_panel,
        }
        loop.call_soon_threadsafe(queue.put_nowait, payload)

    def worker() -> None:
        try:
            reload_settings()
            from src.api import generate_pipeline_result

            result = generate_pipeline_result(topic, progress_callback=on_progress)
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "result", "result": serialize_result(result)},
            )
        except PipelineValidationError as exc:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "error",
                    "error": {
                        "type": "PipelineValidationError",
                        "message": str(exc),
                    },
                },
            )
        except Exception as exc:  # noqa: BLE001 - surface to client
            logger.exception("pipeline run failed topic=%r", topic)
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "error",
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                },
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    async def event_stream() -> AsyncIterator[bytes]:
        task = asyncio.create_task(asyncio.to_thread(worker))
        try:
            yield _sse({"type": "started", "topic": topic})
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield _sse(item)
            yield _sse({"type": "done"})
        finally:
            await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


def create_app() -> FastAPI:
    """App factory for uvicorn."""
    return app
