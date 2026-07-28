"""API request/response schemas (OpenAPI contract)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "arahus-api"
    version: str = "6.0.0"


class ErrorResponse(BaseModel):
    detail: str


class ProjectCreateRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=512)
    project_id: str | None = Field(
        default=None,
        description="Optional stable id; derived from topic when omitted.",
    )


class ProjectResponse(BaseModel):
    id: str
    topic: str
    status: str
    created_at: str
    updated_at: str
    last_run_id: str | None = None
    scene_count: int = 0
    has_memory: bool = False
    has_storyboard: bool = False


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]
    count: int


class GenerateRequest(BaseModel):
    """Optional overrides when kicking off pipeline generation."""

    sync_studio: bool = Field(
        default=True,
        description="Sync Storyboard Studio document after pipeline completes.",
    )


class GenerateAcceptedResponse(BaseModel):
    project_id: str
    topic: str
    status: str = "generating"
    message: str = "Pipeline generation started"
    websocket_url: str


class GenerateSyncResponse(BaseModel):
    project_id: str
    topic: str
    status: str
    run_id: str | None = None
    scene_count: int = 0
    review_score: float | None = None
    storyboard: dict[str, Any] | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class ScenePatchRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    goal: str | None = None
    camera: str | None = None
    emotion: str | None = None
    lighting: str | None = None
    image_prompt: str | None = None
    negative_prompt: str | None = None
    characters: list[str] | None = None
    location: str | None = None
    continuity: str | None = None
    status: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0.1)


class SceneReorderRequest(BaseModel):
    scene_ids: list[int] = Field(min_length=1)


class SceneActionRequest(BaseModel):
    project_id: str = Field(min_length=1)
    dry_run: bool = False
    profile: str | None = None


class SceneMediaResponse(BaseModel):
    project_id: str
    scene_id: int
    status: str
    dry_run: bool = False
    url: str | None = None
    asset_id: int | None = None
    estimate: dict[str, Any] | None = None
    storyboard_scene: dict[str, Any] | None = None


class AssetItem(BaseModel):
    id: int
    kind: str
    slug: str
    label: str
    refs: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetListResponse(BaseModel):
    project_id: str | None = None
    assets: list[AssetItem]
    count: int


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    project_id: str | None = None
    selected_scene_id: int | None = Field(default=None, ge=1)


class ChatResponse(BaseModel):
    reply: str
    project_id: str | None = None
    suggestions: list[str] = Field(default_factory=list)
    commands: list[dict[str, Any]] = Field(default_factory=list)
    preview: dict[str, Any] | None = None
    proposal_id: str | None = None
    can_undo: bool = False
    can_redo: bool = False


class ChatExecuteRequest(BaseModel):
    project_id: str = Field(min_length=1)
    proposal_id: str | None = None
    run_media: bool = True


class ChatUndoRequest(BaseModel):
    project_id: str = Field(min_length=1)


class ChatHistoryResponse(BaseModel):
    project_id: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    pending_proposal_id: str | None = None
    can_undo: bool = False
    can_redo: bool = False


class ChatExecuteResponse(BaseModel):
    reply: str
    project_id: str
    proposal_id: str | None = None
    commands: list[dict[str, Any]] = Field(default_factory=list)
    storyboard: dict[str, Any] | None = None
    can_undo: bool = False
    can_redo: bool = False
    notes: list[str] = Field(default_factory=list)


class ExportResponse(BaseModel):
    project_id: str
    format: Literal["json"] = "json"
    project: dict[str, Any]
    storyboard: dict[str, Any] | None = None
    memory: dict[str, Any] | None = None
    timeline: dict[str, Any] | None = None


class TimelineSyncRequest(BaseModel):
    preserve_non_video: bool = True


class TimelineClipMoveRequest(BaseModel):
    start_seconds: float = Field(ge=0.0)
    track_id: str | None = None


class TimelineClipResizeRequest(BaseModel):
    duration_seconds: float = Field(gt=0.05)


class TimelineReorderRequest(BaseModel):
    track_id: str
    clip_ids: list[str] = Field(min_length=1)


class TimelineTrimRequest(BaseModel):
    in_point: float | None = Field(default=None, ge=0.0)
    out_point: float | None = Field(default=None, gt=0.0)


class TimelineSplitRequest(BaseModel):
    at_seconds: float = Field(ge=0.0)


class TimelineMergeRequest(BaseModel):
    clip_ids: list[str] = Field(min_length=2)


class TimelineTransitionRequest(BaseModel):
    transition_in: str | None = None
    transition_out: str | None = None
    transition_duration: float | None = Field(default=None, ge=0.0)


class TimelineSeekRequest(BaseModel):
    seconds: float = Field(ge=0.0)


class TimelineExportRequest(BaseModel):
    format: Literal["mp4"] = "mp4"
    aspect: Literal["16:9", "9:16", "1:1"] = "16:9"


class ProgressEvent(BaseModel):
    type: str
    project_id: str
    message: str = ""
    fraction: float | None = None
    stages: dict[str, float] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
