"""Orchestration events published on the shared EventBus."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.events.event_bus import Event


@dataclass(frozen=True)
class OrchestrationStarted(Event):
    run_id: str = ""
    graph_name: str = ""


@dataclass(frozen=True)
class OrchestrationCompleted(Event):
    run_id: str = ""
    status: str = ""
    success_rate: float = 0.0
    total_cost_usd: float = 0.0
    total_execution_time_ms: float = 0.0


@dataclass(frozen=True)
class NodeStarted(Event):
    run_id: str = ""
    node_id: str = ""
    agent_name: str = ""
    attempt: int = 0


@dataclass(frozen=True)
class NodeCompleted(Event):
    run_id: str = ""
    node_id: str = ""
    agent_name: str = ""
    status: str = ""
    execution_time_ms: float = 0.0
    cost_usd: float = 0.0
    output_type: str = ""


@dataclass(frozen=True)
class NodeFailed(Event):
    run_id: str = ""
    node_id: str = ""
    agent_name: str = ""
    attempt: int = 0
    error: str = ""
    will_retry: bool = False


@dataclass(frozen=True)
class CheckpointReached(Event):
    """Manual intervention required before the graph continues."""

    run_id: str = ""
    node_id: str = ""
    agent_name: str = ""
    checkpoint_token: str = ""


@dataclass(frozen=True)
class InterventionResolved(Event):
    run_id: str = ""
    node_id: str = ""
    action: str = ""
    message: str = ""


@dataclass(frozen=True)
class OrchestrationCancelled(Event):
    run_id: str = ""
    node_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class AgentMessage(Event):
    """Inter-agent structured message on the EventBus (no free-form side channels)."""

    run_id: str = ""
    from_node: str = ""
    to_node: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
