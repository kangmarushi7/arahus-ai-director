"""AI Copilot chat routes — propose / confirm / undo / history."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.deps import get_copilot_service, get_project_service
from src.api.schemas import (
    ChatExecuteRequest,
    ChatExecuteResponse,
    ChatHistoryResponse,
    ChatRequest,
    ChatResponse,
    ChatUndoRequest,
)
from src.api.services.projects import ProjectService
from src.copilot.service import CopilotService

router = APIRouter(tags=["chat", "copilot"])


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    copilot: Annotated[CopilotService, Depends(get_copilot_service)],
) -> ChatResponse:
    """Parse natural language into structured commands and return a preview.

    Does not mutate the project until ``POST /chat/execute``.
    """
    if not body.project_id:
        return ChatResponse(
            reply=(
                "Arahus Copilot is ready. Pass project_id to edit a storyboard "
                "with natural language."
            ),
            project_id=None,
            suggestions=[
                "POST /projects with a topic to create a project",
                "POST /projects/{id}/generate to run the pipeline",
                "Then POST /chat with project_id to propose edits",
            ],
        )

    try:
        projects.require(body.project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    result = copilot.propose(
        body.project_id,
        body.message,
        selected_scene_id=body.selected_scene_id,
    )
    return ChatResponse(**result)


@router.post("/chat/execute", response_model=ChatExecuteResponse)
def chat_execute(
    body: ChatExecuteRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    copilot: Annotated[CopilotService, Depends(get_copilot_service)],
) -> ChatExecuteResponse:
    """Confirm and execute a pending copilot proposal via existing studio APIs."""
    try:
        projects.require(body.project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        result = copilot.execute(
            body.project_id,
            proposal_id=body.proposal_id,
            run_media=body.run_media,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ChatExecuteResponse(**result)


@router.post("/chat/undo")
def chat_undo(
    body: ChatUndoRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    copilot: Annotated[CopilotService, Depends(get_copilot_service)],
) -> dict[str, Any]:
    try:
        projects.require(body.project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        return copilot.undo(body.project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/chat/redo")
def chat_redo(
    body: ChatUndoRequest,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    copilot: Annotated[CopilotService, Depends(get_copilot_service)],
) -> dict[str, Any]:
    try:
        projects.require(body.project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        return copilot.redo(body.project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/chat", response_model=ChatHistoryResponse)
def chat_history(
    project_id: str,
    projects: Annotated[ProjectService, Depends(get_project_service)],
    copilot: Annotated[CopilotService, Depends(get_copilot_service)],
) -> ChatHistoryResponse:
    try:
        projects.require(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    history = copilot.history(project_id)
    return ChatHistoryResponse(
        project_id=project_id,
        messages=[m.model_dump(mode="json") for m in history.messages],
        pending_proposal_id=history.pending_proposal_id,
        can_undo=copilot.can_undo(project_id),
        can_redo=copilot.can_redo(project_id),
    )


@router.get("/chat/history", response_model=ChatHistoryResponse)
def chat_history_query(
    projects: Annotated[ProjectService, Depends(get_project_service)],
    copilot: Annotated[CopilotService, Depends(get_copilot_service)],
    project_id: str = Query(..., min_length=1),
) -> ChatHistoryResponse:
    return chat_history(project_id, projects, copilot)
