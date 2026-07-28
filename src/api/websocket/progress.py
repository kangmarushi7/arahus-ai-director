"""WebSocket routes for live progress."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from src.api.websocket.hub import progress_hub
from src.security import websocket_api_key_ok
from src.security.paths import safe_path_segment

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/projects/{project_id}")
async def project_progress_ws(websocket: WebSocket, project_id: str) -> None:
    """Stream live progress / status events for a project."""
    api_key = websocket.query_params.get("api_key")
    if not websocket_api_key_ok(api_key):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    safe_id = safe_path_segment(project_id)
    await websocket.accept()
    queue = await progress_hub.subscribe(safe_id)
    await progress_hub.publish(
        safe_id,
        {
            "type": "subscribed",
            "message": f"Subscribed to project {safe_id}",
        },
    )
    try:
        while True:
            get_event = asyncio.create_task(queue.get())
            get_client = asyncio.create_task(websocket.receive_text())
            done, pending = await asyncio.wait(
                {get_event, get_client},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if get_event in done:
                event = get_event.result()
                await websocket.send_json(event)
            if get_client in done:
                # Client pings / ignore payload; disconnect raises below.
                _ = get_client.result()
    except WebSocketDisconnect:
        logger.info("event=ws_disconnect project_id=%r", safe_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("event=ws_error project_id=%r error=%s", safe_id, exc)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
    finally:
        await progress_hub.unsubscribe(safe_id, queue)
