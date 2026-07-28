"""Orchestrator metrics — health, timing, cost, success."""

from __future__ import annotations

from src.orchestration.models import (
    AgentHealth,
    ExecutionGraph,
    NodeStatus,
    OrchestratorMetrics,
    _utc_iso,
)


def compute_metrics(graph: ExecutionGraph) -> OrchestratorMetrics:
    """Derive aggregate metrics from node runtimes."""
    nodes = list(graph.nodes.values())
    completed = sum(1 for n in nodes if n.status == NodeStatus.SUCCESS)
    failed = sum(1 for n in nodes if n.status == NodeStatus.FAILED)
    cancelled = sum(1 for n in nodes if n.status == NodeStatus.CANCELLED)
    total = len(nodes)
    finished = completed + failed + cancelled + sum(
        1 for n in nodes if n.status == NodeStatus.SKIPPED
    )
    success_rate = (completed / finished) if finished else 0.0
    total_time = sum(n.metrics.execution_time_ms for n in nodes)
    total_cost = sum(n.metrics.cost_usd for n in nodes)

    by_agent: dict[str, list] = {}
    for node in nodes:
        by_agent.setdefault(node.spec.agent_name, []).append(node)

    health: list[AgentHealth] = []
    for agent_name, agent_nodes in by_agent.items():
        attempts = sum(n.metrics.attempts for n in agent_nodes)
        successes = sum(n.metrics.success_count for n in agent_nodes)
        rate = (successes / attempts) if attempts else 1.0
        avg_ms = (
            sum(n.metrics.execution_time_ms for n in agent_nodes) / len(agent_nodes)
            if agent_nodes
            else 0.0
        )
        cost = sum(n.metrics.cost_usd for n in agent_nodes)
        last = agent_nodes[-1].status
        healthy = last not in (NodeStatus.FAILED,) and rate >= 0.5
        health.append(
            AgentHealth(
                agent_name=agent_name,
                healthy=healthy,
                success_rate=min(1.0, max(0.0, rate)),
                avg_execution_time_ms=avg_ms,
                total_cost_usd=cost,
                runs=len(agent_nodes),
                last_status=last,
                message="ok" if healthy else "degraded",
            )
        )

    return OrchestratorMetrics(
        run_id=graph.id,
        total_nodes=total,
        completed_nodes=completed,
        failed_nodes=failed,
        cancelled_nodes=cancelled,
        success_rate=success_rate,
        total_execution_time_ms=total_time,
        total_cost_usd=total_cost,
        agent_health=health,
        started_at=graph.started_at,
        finished_at=graph.finished_at or (_utc_iso() if finished == total else None),
    )
