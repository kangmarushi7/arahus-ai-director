"""Autonomous multi-agent orchestration (Sprint 7.0).

Wraps existing agents via runners — agent implementations are not modified.
``DirectorPipeline.generate(topic)`` remains the backward-compatible entrypoint.
"""

from __future__ import annotations

from src.orchestration.orchestrator import AgentOrchestrator, OrchestrationError
from src.orchestration.store import OrchestrationStore
from src.orchestration.workflow import (
    creative_workflow_specs,
    wire_creative_agents,
)

__all__ = [
    "AgentOrchestrator",
    "OrchestrationError",
    "OrchestrationStore",
    "creative_workflow_specs",
    "wire_creative_agents",
]
