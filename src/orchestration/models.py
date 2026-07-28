"""Multi-agent orchestration models — structured outputs only."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import Field

from src.models.base import StrictModel


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class NodeStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"
    WAITING_INTERVENTION = "waiting_intervention"
    SKIPPED = "skipped"


class GraphStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InterventionAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    OVERRIDE = "override"
    SKIP = "skip"


class AgentNodeSpec(StrictModel):
    """Declarative node in an execution DAG."""

    id: str
    agent_name: str
    depends_on: list[str] = Field(default_factory=list)
    max_retries: int = Field(default=2, ge=0)
    checkpoint: bool = False
    parallel_safe: bool = True
    description: str = ""
    cost_estimate_usd: float = Field(default=0.0, ge=0.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StructuredAgentOutput(StrictModel):
    """Envelope for every agent node result (structured payloads only)."""

    agent_name: str
    node_id: str
    output_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc_iso)


class NodeMetrics(StrictModel):
    attempts: int = 0
    success_count: int = 0
    failure_count: int = 0
    execution_time_ms: float = 0.0
    cost_usd: float = 0.0
    last_error: str | None = None


class AgentHealth(StrictModel):
    agent_name: str
    healthy: bool = True
    success_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    avg_execution_time_ms: float = 0.0
    total_cost_usd: float = 0.0
    runs: int = 0
    last_status: NodeStatus | None = None
    message: str = "ok"


class OrchestratorMetrics(StrictModel):
    """Aggregate health / timing / cost / success for a run or process."""

    run_id: str
    total_nodes: int = 0
    completed_nodes: int = 0
    failed_nodes: int = 0
    cancelled_nodes: int = 0
    success_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    total_execution_time_ms: float = 0.0
    total_cost_usd: float = 0.0
    agent_health: list[AgentHealth] = Field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None


class NodeRuntime(StrictModel):
    """Mutable per-node execution state."""

    spec: AgentNodeSpec
    status: NodeStatus = NodeStatus.PENDING
    attempt: int = 0
    output: StructuredAgentOutput | None = None
    error: str | None = None
    metrics: NodeMetrics = Field(default_factory=NodeMetrics)
    started_at: str | None = None
    finished_at: str | None = None
    checkpoint_token: str | None = None
    intervention: dict[str, Any] | None = None


class ManualIntervention(StrictModel):
    run_id: str
    node_id: str
    action: InterventionAction
    message: str = ""
    override_payload: dict[str, Any] | None = None
    created_at: str = Field(default_factory=_utc_iso)


class ExecutionGraph(StrictModel):
    """Persisted DAG for replay / debugging / recovery."""

    id: str = Field(default_factory=lambda: _new_id("orch"))
    name: str = "creative_workflow"
    topic: str = ""
    status: GraphStatus = GraphStatus.PENDING
    nodes: dict[str, NodeRuntime] = Field(default_factory=dict)
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    metrics: OrchestratorMetrics | None = None
    created_at: str = Field(default_factory=_utc_iso)
    updated_at: str = Field(default_factory=_utc_iso)
    started_at: str | None = None
    finished_at: str | None = None
    cancel_requested: bool = False
    resume_from: str | None = None
    version: int = Field(default=1, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def touch(self) -> ExecutionGraph:
        return self.model_copy(
            update={"updated_at": _utc_iso(), "version": self.version + 1}
        )

    def node(self, node_id: str) -> NodeRuntime:
        try:
            return self.nodes[node_id]
        except KeyError as exc:
            raise KeyError(f"Node {node_id!r} not found") from exc

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionGraph:
        return cls.model_validate(data)
