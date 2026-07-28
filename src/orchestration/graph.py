"""DAG helpers — dependency validation and parallel ready-sets."""

from __future__ import annotations

from src.orchestration.models import AgentNodeSpec, ExecutionGraph, NodeStatus


class GraphValidationError(ValueError):
    """Raised when a node DAG is invalid."""


def validate_specs(specs: list[AgentNodeSpec]) -> None:
    ids = [spec.id for spec in specs]
    if len(ids) != len(set(ids)):
        raise GraphValidationError("Duplicate node ids in graph")
    known = set(ids)
    for spec in specs:
        for dep in spec.depends_on:
            if dep not in known:
                raise GraphValidationError(
                    f"Node {spec.id!r} depends on unknown node {dep!r}"
                )
            if dep == spec.id:
                raise GraphValidationError(f"Node {spec.id!r} depends on itself")
    # Cycle detection via DFS
    adj = {spec.id: list(spec.depends_on) for spec in specs}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visited:
            return
        if node_id in visiting:
            raise GraphValidationError(f"Cycle detected at node {node_id!r}")
        visiting.add(node_id)
        for dep in adj[node_id]:
            visit(dep)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in ids:
        visit(node_id)


def deps_satisfied(graph: ExecutionGraph, node_id: str) -> bool:
    runtime = graph.node(node_id)
    for dep in runtime.spec.depends_on:
        dep_status = graph.node(dep).status
        if dep_status not in (NodeStatus.SUCCESS, NodeStatus.SKIPPED):
            return False
    return True


def ready_nodes(graph: ExecutionGraph) -> list[str]:
    """Return node ids that can run now (deps met, not finished/cancelled)."""
    ready: list[str] = []
    for node_id, runtime in graph.nodes.items():
        if runtime.status not in (
            NodeStatus.PENDING,
            NodeStatus.READY,
            NodeStatus.RETRYING,
        ):
            continue
        if deps_satisfied(graph, node_id):
            ready.append(node_id)
    return ready


def parallel_batches(graph: ExecutionGraph, ready: list[str]) -> list[list[str]]:
    """Split ready nodes into parallel-safe batches.

    Nodes marked ``parallel_safe=False`` run alone. Others in the same ready
    set may execute concurrently.
    """
    solo = [nid for nid in ready if not graph.node(nid).spec.parallel_safe]
    group = [nid for nid in ready if graph.node(nid).spec.parallel_safe]
    batches: list[list[str]] = []
    if group:
        batches.append(group)
    for nid in solo:
        batches.append([nid])
    return batches
