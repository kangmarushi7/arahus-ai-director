"""AgentOrchestrator — DAG execution with EventBus, checkpoints, recovery."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Protocol, runtime_checkable

from src.events import Event, EventBus
from src.orchestration.events import (
    AgentMessage,
    CheckpointReached,
    InterventionResolved,
    NodeCompleted,
    NodeFailed,
    NodeStarted,
    OrchestrationCancelled,
    OrchestrationCompleted,
    OrchestrationStarted,
)
from src.orchestration.graph import (
    GraphValidationError,
    parallel_batches,
    ready_nodes,
    validate_specs,
)
from src.orchestration.metrics import compute_metrics
from src.orchestration.models import (
    AgentNodeSpec,
    ExecutionGraph,
    GraphStatus,
    InterventionAction,
    ManualIntervention,
    NodeRuntime,
    NodeStatus,
    StructuredAgentOutput,
    _utc_iso,
)
from src.orchestration.store import OrchestrationStore
from src.models.base import StrictModel

logger = logging.getLogger(__name__)


@runtime_checkable
class AgentRunner(Protocol):
    """Callable bound to an existing agent — must return structured data."""

    def __call__(
        self,
        *,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        node_id: str,
        run_id: str,
    ) -> StrictModel | StructuredAgentOutput | dict[str, Any]:
        ...


class OrchestrationError(RuntimeError):
    """Raised when a graph cannot complete successfully."""


class AgentOrchestrator:
    """Coordinates multi-agent workflows over the shared :class:`EventBus`.

    Does not modify agent implementations — callers register runners that
    invoke existing ``agent.run(...)`` methods and return structured outputs.
    """

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        store: OrchestrationStore | None = None,
        max_workers: int = 4,
        auto_approve_checkpoints: bool = False,
        intervention_poll_seconds: float = 0.05,
        intervention_timeout_seconds: float | None = 30.0,
    ) -> None:
        self._bus = event_bus or EventBus()
        self._store = store or OrchestrationStore()
        self._max_workers = max(1, max_workers)
        self._auto_approve = auto_approve_checkpoints
        self._poll = max(0.01, intervention_poll_seconds)
        self._intervention_timeout = intervention_timeout_seconds
        self._runners: dict[str, AgentRunner] = {}
        self._cancel_flags: dict[str, threading.Event] = {}
        self._interventions: dict[str, ManualIntervention] = {}
        self._lock = threading.RLock()
        self._active: dict[str, ExecutionGraph] = {}

    @property
    def event_bus(self) -> EventBus:
        return self._bus

    @property
    def store(self) -> OrchestrationStore:
        return self._store

    def register_runner(self, agent_name: str, runner: AgentRunner) -> None:
        """Bind ``agent_name`` to a structured-output runner."""
        self._runners[agent_name] = runner

    def build_graph(
        self,
        specs: list[AgentNodeSpec],
        *,
        topic: str = "",
        name: str = "creative_workflow",
        inputs: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionGraph:
        validate_specs(specs)
        for spec in specs:
            if spec.agent_name not in self._runners:
                raise GraphValidationError(
                    f"No runner registered for agent {spec.agent_name!r}"
                )
        nodes = {
            spec.id: NodeRuntime(spec=spec, status=NodeStatus.PENDING)
            for spec in specs
        }
        graph = ExecutionGraph(
            name=name,
            topic=topic,
            nodes=nodes,
            inputs=dict(inputs or {}),
            metadata=dict(metadata or {}),
        )
        graph.metrics = compute_metrics(graph)
        self._store.save(graph)
        return graph

    def cancel(self, run_id: str, *, reason: str = "cancelled") -> ExecutionGraph:
        with self._lock:
            flag = self._cancel_flags.setdefault(run_id, threading.Event())
            flag.set()
            graph = self._active.get(run_id) or self._store.load(run_id)
            if graph is None:
                raise KeyError(f"Run {run_id!r} not found")
            graph = graph.model_copy(
                update={
                    "cancel_requested": True,
                    "status": GraphStatus.CANCELLED,
                    "finished_at": _utc_iso(),
                }
            ).touch()
            for node_id, runtime in list(graph.nodes.items()):
                if runtime.status in (
                    NodeStatus.PENDING,
                    NodeStatus.READY,
                    NodeStatus.RUNNING,
                    NodeStatus.RETRYING,
                    NodeStatus.WAITING_INTERVENTION,
                ):
                    graph.nodes[node_id] = runtime.model_copy(
                        update={
                            "status": NodeStatus.CANCELLED,
                            "finished_at": _utc_iso(),
                            "error": reason,
                        }
                    )
            graph.metrics = compute_metrics(graph)
            self._active[run_id] = graph
            self._store.save(graph)
        self._publish(
            OrchestrationCancelled(topic=graph.topic, run_id=run_id, reason=reason)
        )
        return graph

    def intervene(
        self,
        run_id: str,
        node_id: str,
        action: InterventionAction | str,
        *,
        message: str = "",
        override_payload: dict[str, Any] | None = None,
    ) -> ManualIntervention:
        """Resolve a manual checkpoint for ``node_id``."""
        action_id = (
            action
            if isinstance(action, InterventionAction)
            else InterventionAction(action)
        )
        record = ManualIntervention(
            run_id=run_id,
            node_id=node_id,
            action=action_id,
            message=message,
            override_payload=override_payload,
        )
        key = f"{run_id}:{node_id}"
        with self._lock:
            self._interventions[key] = record
        self._publish(
            InterventionResolved(
                topic=run_id,
                run_id=run_id,
                node_id=node_id,
                action=action_id.value,
                message=message,
            )
        )
        return record

    def load(self, run_id: str) -> ExecutionGraph | None:
        with self._lock:
            if run_id in self._active:
                return self._active[run_id]
        return self._store.load(run_id)

    def run(
        self,
        graph: ExecutionGraph,
        *,
        resume: bool = False,
    ) -> ExecutionGraph:
        """Execute ``graph`` with parallel ready-sets, retries, and checkpoints."""
        run_id = graph.id
        with self._lock:
            self._cancel_flags.setdefault(run_id, threading.Event())
            if not resume:
                self._cancel_flags[run_id].clear()
            self._active[run_id] = graph

        if not resume or graph.started_at is None:
            graph = graph.model_copy(
                update={
                    "status": GraphStatus.RUNNING,
                    "started_at": graph.started_at or _utc_iso(),
                    "cancel_requested": False,
                }
            ).touch()
        else:
            graph = graph.model_copy(update={"status": GraphStatus.RUNNING}).touch()

        self._persist(graph)
        self._publish(
            OrchestrationStarted(
                topic=graph.topic, run_id=run_id, graph_name=graph.name
            )
        )

        try:
            while True:
                if self._is_cancelled(run_id):
                    return self.cancel(run_id)

                ready = ready_nodes(graph)
                if not ready:
                    if self._all_terminal(graph):
                        break
                    waiting = [
                        n
                        for n, r in graph.nodes.items()
                        if r.status == NodeStatus.WAITING_INTERVENTION
                    ]
                    if waiting:
                        graph = graph.model_copy(
                            update={"status": GraphStatus.PAUSED}
                        ).touch()
                        self._persist(graph)
                        # Block until interventions resolve or cancel/timeout
                        for node_id in waiting:
                            graph = self._await_intervention(graph, node_id)
                        continue
                    # Deadlock / unmet deps with failures
                    break

                for batch in parallel_batches(graph, ready):
                    if self._is_cancelled(run_id):
                        return self.cancel(run_id)
                    if len(batch) == 1 or self._max_workers == 1:
                        for node_id in batch:
                            graph = self._execute_node(graph, node_id)
                    else:
                        graph = self._execute_parallel(graph, batch)

            graph = self._finalize(graph)
            return graph
        except Exception:
            graph = graph.model_copy(
                update={
                    "status": GraphStatus.FAILED,
                    "finished_at": _utc_iso(),
                }
            ).touch()
            graph.metrics = compute_metrics(graph)
            self._persist(graph)
            raise

    def resume(self, run_id: str) -> ExecutionGraph:
        """Resume a paused / partially completed graph from disk."""
        graph = self.load(run_id)
        if graph is None:
            raise KeyError(f"Run {run_id!r} not found")
        # Reset cancelled-but-resumable pending? Keep SUCCESS; requeue FAILED as RETRYING
        nodes = dict(graph.nodes)
        for node_id, runtime in nodes.items():
            if runtime.status == NodeStatus.FAILED:
                nodes[node_id] = runtime.model_copy(
                    update={
                        "status": NodeStatus.RETRYING,
                        "attempt": 0,
                        "error": None,
                        "finished_at": None,
                    }
                )
            elif runtime.status == NodeStatus.CANCELLED:
                nodes[node_id] = runtime.model_copy(
                    update={
                        "status": NodeStatus.PENDING,
                        "attempt": 0,
                        "error": None,
                        "finished_at": None,
                    }
                )
            elif runtime.status == NodeStatus.WAITING_INTERVENTION:
                # leave waiting — intervene() must resolve
                pass
        graph = graph.model_copy(
            update={
                "nodes": nodes,
                "resume_from": run_id,
                "cancel_requested": False,
                "finished_at": None,
            }
        ).touch()
        with self._lock:
            flag = self._cancel_flags.setdefault(run_id, threading.Event())
            flag.clear()
        return self.run(graph, resume=True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _execute_parallel(
        self, graph: ExecutionGraph, batch: list[str]
    ) -> ExecutionGraph:
        results: dict[str, NodeRuntime] = {}
        with ThreadPoolExecutor(max_workers=min(self._max_workers, len(batch))) as pool:
            futures = {
                pool.submit(self._run_node_isolated, graph, node_id): node_id
                for node_id in batch
            }
            for future in as_completed(futures):
                node_id = futures[future]
                results[node_id] = future.result()

        nodes = dict(graph.nodes)
        outputs = dict(graph.outputs)
        for node_id, runtime in results.items():
            nodes[node_id] = runtime
            if runtime.status == NodeStatus.SUCCESS and runtime.output is not None:
                outputs[node_id] = runtime.output.payload
                self._emit_agent_message(graph, node_id, runtime)
        graph = graph.model_copy(update={"nodes": nodes, "outputs": outputs}).touch()
        graph.metrics = compute_metrics(graph)
        self._persist(graph)
        return graph

    def _run_node_isolated(
        self, graph: ExecutionGraph, node_id: str
    ) -> NodeRuntime:
        """Execute one node and return updated runtime (no graph mutation races)."""
        # Work on a shallow copy context from graph inputs/outputs snapshot
        return self._attempt_node(graph, node_id)

    def _execute_node(self, graph: ExecutionGraph, node_id: str) -> ExecutionGraph:
        runtime = self._attempt_node(graph, node_id)
        nodes = dict(graph.nodes)
        nodes[node_id] = runtime
        outputs = dict(graph.outputs)
        if runtime.status == NodeStatus.SUCCESS and runtime.output is not None:
            outputs[node_id] = runtime.output.payload
            self._emit_agent_message(graph, node_id, runtime)
        graph = graph.model_copy(update={"nodes": nodes, "outputs": outputs}).touch()
        graph.metrics = compute_metrics(graph)
        self._persist(graph)

        if (
            runtime.status == NodeStatus.SUCCESS
            and runtime.spec.checkpoint
            and runtime.intervention is None
        ):
            graph = self._enter_checkpoint(graph, node_id)
        return graph

    def _attempt_node(self, graph: ExecutionGraph, node_id: str) -> NodeRuntime:
        runtime = graph.node(node_id)
        spec = runtime.spec
        runner = self._runners[spec.agent_name]
        max_attempts = spec.max_retries + 1
        attempt = runtime.attempt
        metrics = runtime.metrics.model_copy()
        last_error: str | None = None

        while attempt < max_attempts:
            if self._is_cancelled(graph.id):
                return runtime.model_copy(
                    update={
                        "status": NodeStatus.CANCELLED,
                        "finished_at": _utc_iso(),
                        "error": "cancelled",
                        "attempt": attempt,
                        "metrics": metrics,
                    }
                )

            attempt += 1
            metrics.attempts += 1
            started = time.perf_counter()
            self._publish(
                NodeStarted(
                    topic=graph.topic,
                    run_id=graph.id,
                    node_id=node_id,
                    agent_name=spec.agent_name,
                    attempt=attempt,
                )
            )
            try:
                raw = runner(
                    inputs=dict(graph.inputs),
                    outputs=dict(graph.outputs),
                    node_id=node_id,
                    run_id=graph.id,
                )
                output = self._coerce_output(raw, spec.agent_name, node_id)
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                cost = float(spec.cost_estimate_usd)
                metrics.execution_time_ms += elapsed_ms
                metrics.cost_usd += cost
                metrics.success_count += 1
                metrics.last_error = None
                result = runtime.model_copy(
                    update={
                        "status": NodeStatus.SUCCESS,
                        "attempt": attempt,
                        "output": output,
                        "error": None,
                        "metrics": metrics,
                        "started_at": runtime.started_at or _utc_iso(),
                        "finished_at": _utc_iso(),
                    }
                )
                self._publish(
                    NodeCompleted(
                        topic=graph.topic,
                        run_id=graph.id,
                        node_id=node_id,
                        agent_name=spec.agent_name,
                        status=NodeStatus.SUCCESS.value,
                        execution_time_ms=elapsed_ms,
                        cost_usd=cost,
                        output_type=output.output_type,
                    )
                )
                return result
            except Exception as exc:  # noqa: BLE001
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                metrics.execution_time_ms += elapsed_ms
                metrics.failure_count += 1
                last_error = str(exc)
                metrics.last_error = last_error
                will_retry = attempt < max_attempts
                self._publish(
                    NodeFailed(
                        topic=graph.topic,
                        run_id=graph.id,
                        node_id=node_id,
                        agent_name=spec.agent_name,
                        attempt=attempt,
                        error=last_error,
                        will_retry=will_retry,
                    )
                )
                if will_retry:
                    runtime = runtime.model_copy(
                        update={
                            "status": NodeStatus.RETRYING,
                            "attempt": attempt,
                            "error": last_error,
                            "metrics": metrics,
                            "started_at": runtime.started_at or _utc_iso(),
                        }
                    )
                    continue
                break

        return runtime.model_copy(
            update={
                "status": NodeStatus.FAILED,
                "attempt": attempt,
                "error": last_error or "unknown error",
                "metrics": metrics,
                "started_at": runtime.started_at or _utc_iso(),
                "finished_at": _utc_iso(),
            }
        )

    def _enter_checkpoint(
        self, graph: ExecutionGraph, node_id: str
    ) -> ExecutionGraph:
        token = uuid.uuid4().hex[:10]
        runtime = graph.node(node_id).model_copy(
            update={
                "status": NodeStatus.WAITING_INTERVENTION,
                "checkpoint_token": token,
                "finished_at": None,
            }
        )
        nodes = dict(graph.nodes)
        nodes[node_id] = runtime
        graph = graph.model_copy(
            update={"nodes": nodes, "status": GraphStatus.PAUSED}
        ).touch()
        self._persist(graph)
        self._publish(
            CheckpointReached(
                topic=graph.topic,
                run_id=graph.id,
                node_id=node_id,
                agent_name=runtime.spec.agent_name,
                checkpoint_token=token,
            )
        )
        if self._auto_approve:
            self.intervene(
                graph.id,
                node_id,
                InterventionAction.APPROVE,
                message="auto-approved",
            )
        return self._await_intervention(graph, node_id)

    def _await_intervention(
        self, graph: ExecutionGraph, node_id: str
    ) -> ExecutionGraph:
        key = f"{graph.id}:{node_id}"
        deadline = None
        if self._intervention_timeout is not None:
            deadline = time.monotonic() + self._intervention_timeout

        while True:
            if self._is_cancelled(graph.id):
                return self.cancel(graph.id)

            with self._lock:
                record = self._interventions.pop(key, None)

            if record is not None:
                return self._apply_intervention(graph, node_id, record)

            if deadline is not None and time.monotonic() >= deadline:
                # Timeout → auto-approve to avoid hanging tests/prod without operator
                self.intervene(
                    graph.id,
                    node_id,
                    InterventionAction.APPROVE,
                    message="intervention timeout — auto-approved",
                )
                continue

            time.sleep(self._poll)
            # Refresh graph from active in case cancel mutated it
            loaded = self.load(graph.id)
            if loaded is not None:
                graph = loaded

    def _apply_intervention(
        self,
        graph: ExecutionGraph,
        node_id: str,
        record: ManualIntervention,
    ) -> ExecutionGraph:
        runtime = graph.node(node_id)
        nodes = dict(graph.nodes)
        outputs = dict(graph.outputs)

        if record.action == InterventionAction.APPROVE:
            nodes[node_id] = runtime.model_copy(
                update={
                    "status": NodeStatus.SUCCESS,
                    "intervention": record.model_dump(mode="json"),
                    "finished_at": _utc_iso(),
                }
            )
        elif record.action == InterventionAction.SKIP:
            nodes[node_id] = runtime.model_copy(
                update={
                    "status": NodeStatus.SKIPPED,
                    "intervention": record.model_dump(mode="json"),
                    "finished_at": _utc_iso(),
                }
            )
        elif record.action == InterventionAction.REJECT:
            nodes[node_id] = runtime.model_copy(
                update={
                    "status": NodeStatus.FAILED,
                    "error": record.message or "rejected at checkpoint",
                    "intervention": record.model_dump(mode="json"),
                    "finished_at": _utc_iso(),
                }
            )
        elif record.action == InterventionAction.OVERRIDE:
            payload = record.override_payload or {}
            output = StructuredAgentOutput(
                agent_name=runtime.spec.agent_name,
                node_id=node_id,
                output_type="override",
                payload=payload,
            )
            nodes[node_id] = runtime.model_copy(
                update={
                    "status": NodeStatus.SUCCESS,
                    "output": output,
                    "intervention": record.model_dump(mode="json"),
                    "finished_at": _utc_iso(),
                }
            )
            outputs[node_id] = payload

        graph = graph.model_copy(
            update={
                "nodes": nodes,
                "outputs": outputs,
                "status": GraphStatus.RUNNING,
            }
        ).touch()
        graph.metrics = compute_metrics(graph)
        self._persist(graph)
        return graph

    def _finalize(self, graph: ExecutionGraph) -> ExecutionGraph:
        failed = any(n.status == NodeStatus.FAILED for n in graph.nodes.values())
        cancelled = any(
            n.status == NodeStatus.CANCELLED for n in graph.nodes.values()
        ) or graph.cancel_requested
        if cancelled and not any(
            n.status == NodeStatus.SUCCESS for n in graph.nodes.values()
        ):
            status = GraphStatus.CANCELLED
        elif failed:
            status = GraphStatus.FAILED
        elif cancelled:
            status = GraphStatus.CANCELLED
        else:
            status = GraphStatus.SUCCESS

        graph = graph.model_copy(
            update={
                "status": status,
                "finished_at": _utc_iso(),
            }
        ).touch()
        graph.metrics = compute_metrics(graph)
        self._persist(graph)
        metrics = graph.metrics
        self._publish(
            OrchestrationCompleted(
                topic=graph.topic,
                run_id=graph.id,
                status=status.value,
                success_rate=metrics.success_rate if metrics else 0.0,
                total_cost_usd=metrics.total_cost_usd if metrics else 0.0,
                total_execution_time_ms=(
                    metrics.total_execution_time_ms if metrics else 0.0
                ),
            )
        )
        if status == GraphStatus.FAILED:
            raise OrchestrationError(
                f"Orchestration {graph.id} failed — see persisted graph for details"
            )
        return graph

    def _coerce_output(
        self,
        raw: StrictModel | StructuredAgentOutput | dict[str, Any],
        agent_name: str,
        node_id: str,
    ) -> StructuredAgentOutput:
        if isinstance(raw, StructuredAgentOutput):
            return raw
        if isinstance(raw, StrictModel):
            return StructuredAgentOutput(
                agent_name=agent_name,
                node_id=node_id,
                output_type=type(raw).__name__,
                payload=raw.model_dump(mode="json"),
            )
        if isinstance(raw, dict):
            return StructuredAgentOutput(
                agent_name=agent_name,
                node_id=node_id,
                output_type="dict",
                payload=raw,
            )
        raise TypeError(
            f"Agent {agent_name!r} must return StrictModel, StructuredAgentOutput, "
            f"or dict — got {type(raw).__name__}"
        )

    def _emit_agent_message(
        self, graph: ExecutionGraph, node_id: str, runtime: NodeRuntime
    ) -> None:
        """Publish structured output to downstream dependents via EventBus."""
        dependents = [
            nid
            for nid, node in graph.nodes.items()
            if node_id in node.spec.depends_on
        ]
        for dep in dependents:
            self._publish(
                AgentMessage(
                    topic=graph.topic,
                    run_id=graph.id,
                    from_node=node_id,
                    to_node=dep,
                    payload=runtime.output.payload if runtime.output else {},
                )
            )

    def _all_terminal(self, graph: ExecutionGraph) -> bool:
        terminal = {
            NodeStatus.SUCCESS,
            NodeStatus.FAILED,
            NodeStatus.CANCELLED,
            NodeStatus.SKIPPED,
        }
        return all(n.status in terminal for n in graph.nodes.values())

    def _is_cancelled(self, run_id: str) -> bool:
        with self._lock:
            flag = self._cancel_flags.get(run_id)
            return bool(flag and flag.is_set())

    def _persist(self, graph: ExecutionGraph) -> None:
        with self._lock:
            self._active[graph.id] = graph
        self._store.save(graph)

    def _publish(self, event: Event) -> None:
        try:
            self._bus.publish(event)
        except Exception as exc:  # noqa: BLE001 - bus must not fail the run
            logger.warning(
                "event=orch_bus_publish_failed type=%s error=%s",
                type(event).__name__,
                exc,
            )
