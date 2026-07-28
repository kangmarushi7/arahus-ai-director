"""Sprint 7.0 — AgentOrchestrator integration and recovery tests."""

from __future__ import annotations

import inspect
import threading
import time
from pathlib import Path

import pytest

from src.events import EventBus
from src.models.research import ResearchResult
from src.models.review import ReviewResult
from src.models.storyboard import DirectorPlan, Scene, Storyboard
from src.orchestration.events import (
    CheckpointReached,
    NodeCompleted,
    OrchestrationCompleted,
    OrchestrationStarted,
)
from src.orchestration.models import (
    AgentNodeSpec,
    GraphStatus,
    InterventionAction,
    NodeStatus,
)
from src.orchestration.orchestrator import AgentOrchestrator, OrchestrationError
from src.orchestration.store import OrchestrationStore
from src.orchestration.workflow import (
    creative_workflow_specs,
    make_echo_runner,
    parallel_demo_specs,
    wire_creative_agents,
)
from src.pipeline import DirectorPipeline


class _FakeResearch:
    def run(self, topic: str, domain_info=None):
        return ResearchResult(
            topic=topic,
            time_period="1800s",
            location="Alps",
            key_people=["Napoleon"],
            historical_notes=["crossing"],
        )


class _FakeDirector:
    def run(self, topic: str, research, domain_info=None, character_bible: str = ""):
        scenes = [
            Scene(id=i, title=f"S{i}", description=f"Scene {i} with Napoleon")
            for i in range(1, 5)
        ]
        return DirectorPlan(topic=topic, scenes=scenes)


class _FakePrompt:
    def run(
        self,
        plan,
        research,
        domain_info=None,
        prompt_context=None,
        character_bible: str = "",
        project_memory=None,
    ):
        scenes = [
            Scene(
                id=s.id,
                title=s.title,
                description=s.description,
                image_prompt=f"prompt {s.id}",
            )
            for s in plan.scenes
        ]
        return Storyboard(topic=plan.topic, scenes=scenes)


class _FakeReview:
    def run(self, storyboard, domain_info=None):
        return ReviewResult(
            overall_score=92,
            domain_accuracy=90,
            visual_quality=90,
            scene_continuity=90,
            prompt_quality=90,
            approved=True,
        )


class _FailOnceThenOk:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *, inputs, outputs, node_id, run_id):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient failure")
        return {"ok": True, "calls": self.calls}


def test_generate_signature_unchanged() -> None:
    sig = inspect.signature(DirectorPipeline.generate)
    params = list(sig.parameters)
    assert params == ["self", "topic", "progress_callback"]


def test_parallel_execution_and_metrics(tmp_path: Path) -> None:
    bus = EventBus()
    started: list = []
    completed: list = []
    bus.subscribe(OrchestrationStarted, started.append)
    bus.subscribe(OrchestrationCompleted, completed.append)
    bus.subscribe(NodeCompleted, lambda e: completed.append(e))

    orch = AgentOrchestrator(
        event_bus=bus,
        store=OrchestrationStore(root=tmp_path),
        max_workers=4,
        auto_approve_checkpoints=True,
    )
    for name in ("a", "b", "c", "d"):
        orch.register_runner(name, make_echo_runner(name))

    graph = orch.build_graph(
        parallel_demo_specs(),
        topic="parallel",
        name="parallel_demo",
        inputs={"topic": "parallel"},
    )
    result = orch.run(graph)

    assert result.status == GraphStatus.SUCCESS
    assert set(result.outputs) == {"a", "b", "c", "d"}
    assert result.metrics is not None
    assert result.metrics.completed_nodes == 4
    assert result.metrics.success_rate == 1.0
    assert result.metrics.total_cost_usd > 0
    assert any(h.healthy for h in result.metrics.agent_health)
    assert started and started[0].run_id == result.id
    assert (tmp_path / f"{result.id}.json").is_file()


def test_retries_on_failure(tmp_path: Path) -> None:
    orch = AgentOrchestrator(
        store=OrchestrationStore(root=tmp_path),
        auto_approve_checkpoints=True,
    )
    flaky = _FailOnceThenOk()
    orch.register_runner("flaky", flaky)
    graph = orch.build_graph(
        [
            AgentNodeSpec(
                id="n1",
                agent_name="flaky",
                max_retries=2,
                cost_estimate_usd=0.01,
            )
        ],
        topic="retry",
        inputs={"topic": "retry"},
    )
    result = orch.run(graph)
    assert result.status == GraphStatus.SUCCESS
    assert flaky.calls == 2
    assert result.nodes["n1"].metrics.failure_count == 1
    assert result.nodes["n1"].metrics.success_count == 1


def test_cancellation(tmp_path: Path) -> None:
    orch = AgentOrchestrator(
        store=OrchestrationStore(root=tmp_path),
        auto_approve_checkpoints=False,
        intervention_timeout_seconds=None,
        intervention_poll_seconds=0.02,
    )
    orch.register_runner("a", make_echo_runner("a"))
    orch.register_runner("b", make_echo_runner("b"))

    graph = orch.build_graph(
        [
            AgentNodeSpec(
                id="a",
                agent_name="a",
                checkpoint=True,
                cost_estimate_usd=0.01,
            ),
            AgentNodeSpec(
                id="b",
                agent_name="b",
                depends_on=["a"],
                cost_estimate_usd=0.01,
            ),
        ],
        topic="cancel-me",
        inputs={"topic": "cancel-me"},
    )

    def cancel_at_checkpoint() -> None:
        for _ in range(200):
            loaded = orch.load(graph.id)
            if loaded and loaded.nodes["a"].status == NodeStatus.WAITING_INTERVENTION:
                orch.cancel(graph.id, reason="test cancel")
                return
            time.sleep(0.02)

    thread = threading.Thread(target=cancel_at_checkpoint)
    thread.start()
    result = orch.run(graph)
    thread.join()

    assert result.status == GraphStatus.CANCELLED
    assert result.cancel_requested is True


def test_checkpoint_manual_intervention(tmp_path: Path) -> None:
    bus = EventBus()
    checkpoints: list = []
    bus.subscribe(CheckpointReached, checkpoints.append)

    orch = AgentOrchestrator(
        event_bus=bus,
        store=OrchestrationStore(root=tmp_path),
        auto_approve_checkpoints=False,
        intervention_timeout_seconds=None,
        intervention_poll_seconds=0.02,
    )
    orch.register_runner("a", make_echo_runner("a"))
    orch.register_runner("b", make_echo_runner("b"))

    graph = orch.build_graph(
        [
            AgentNodeSpec(
                id="a",
                agent_name="a",
                checkpoint=True,
                cost_estimate_usd=0.01,
            ),
            AgentNodeSpec(
                id="b",
                agent_name="b",
                depends_on=["a"],
                cost_estimate_usd=0.01,
            ),
        ],
        topic="intervene",
        inputs={"topic": "intervene"},
    )

    def approve_soon() -> None:
        # Wait until checkpoint is reached
        for _ in range(200):
            loaded = orch.load(graph.id)
            if loaded and loaded.nodes["a"].status == NodeStatus.WAITING_INTERVENTION:
                orch.intervene(
                    graph.id,
                    "a",
                    InterventionAction.APPROVE,
                    message="looks good",
                )
                return
            time.sleep(0.02)

    thread = threading.Thread(target=approve_soon)
    thread.start()
    result = orch.run(graph)
    thread.join()

    assert result.status == GraphStatus.SUCCESS
    assert checkpoints
    assert result.nodes["a"].intervention is not None
    assert result.outputs["b"]["agent"] == "b"


def test_checkpoint_recovery_resume(tmp_path: Path) -> None:
    store = OrchestrationStore(root=tmp_path)
    orch = AgentOrchestrator(
        store=store,
        auto_approve_checkpoints=True,
        intervention_timeout_seconds=2.0,
    )
    calls = {"b": 0}

    def a_runner(*, inputs, outputs, node_id, run_id):
        return {"stage": "a"}

    def b_runner(*, inputs, outputs, node_id, run_id):
        calls["b"] += 1
        if calls["b"] == 1:
            raise RuntimeError("boom")
        return {"stage": "b", "from_a": outputs.get("a")}

    orch.register_runner("a", a_runner)
    orch.register_runner("b", b_runner)

    graph = orch.build_graph(
        [
            AgentNodeSpec(id="a", agent_name="a", max_retries=0),
            AgentNodeSpec(
                id="b", agent_name="b", depends_on=["a"], max_retries=0
            ),
        ],
        topic="recover",
        inputs={"topic": "recover"},
    )

    with pytest.raises(OrchestrationError):
        orch.run(graph)

    failed = store.load(graph.id)
    assert failed is not None
    assert failed.nodes["a"].status == NodeStatus.SUCCESS
    assert failed.nodes["b"].status == NodeStatus.FAILED

    # New orchestrator instance (simulates process restart) resumes from disk
    orch2 = AgentOrchestrator(
        store=store,
        auto_approve_checkpoints=True,
        intervention_timeout_seconds=2.0,
    )
    orch2.register_runner("a", a_runner)
    orch2.register_runner("b", b_runner)
    recovered = orch2.resume(graph.id)

    assert recovered.status == GraphStatus.SUCCESS
    assert recovered.nodes["a"].status == NodeStatus.SUCCESS
    assert recovered.nodes["b"].status == NodeStatus.SUCCESS
    assert calls["b"] == 2
    assert recovered.outputs["b"]["from_a"]["stage"] == "a"


def test_creative_workflow_structured_outputs(tmp_path: Path) -> None:
    bus = EventBus()
    orch = AgentOrchestrator(
        event_bus=bus,
        store=OrchestrationStore(root=tmp_path),
        auto_approve_checkpoints=True,
        intervention_timeout_seconds=2.0,
    )
    wire_creative_agents(
        orch,
        research_agent=_FakeResearch(),
        director_agent=_FakeDirector(),
        prompt_agent=_FakePrompt(),
        review_agent=_FakeReview(),
    )
    graph = orch.build_graph(
        creative_workflow_specs(
            checkpoint_after_director=True,
            checkpoint_after_review=True,
        ),
        topic="Napoleon Alps",
        inputs={"topic": "Napoleon Alps"},
    )
    result = orch.run(graph)

    assert result.status == GraphStatus.SUCCESS
    assert "research" in result.outputs
    assert result.outputs["research"]["topic"] == "Napoleon Alps"
    assert result.outputs["director"]["scenes"]
    assert result.outputs["prompt"]["scenes"]
    assert result.outputs["review"]["approved"] is True
    assert result.metrics is not None
    assert len(result.metrics.agent_health) == 4


def test_pipeline_generate_still_works_and_orchestrator_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ALLOW_STUB_SERVICES", "true")
    monkeypatch.setenv("PROMPT_OPTIMIZER_ENABLED", "false")
    monkeypatch.setenv("PERSIST_PIPELINE_RUNS", "false")
    from src.config import reload_settings
    from src.domain.models import DomainInfo, DomainType
    from src.domain.prompt_context import DomainPromptContext
    from src.models.image import ImageResult

    reload_settings()

    class _FakeDomainService:
        def detect(self, topic: str) -> DomainInfo:
            return DomainInfo(
                domain=DomainType.GENERAL, confidence=0.9, reasoning="t"
            )

        def get_prompt_context(self, domain: DomainType) -> DomainPromptContext:
            return DomainPromptContext(
                domain=domain,
                style="s",
                camera="c",
                lighting="l",
                color_palette="p",
                composition="co",
                quality_tags=["q"],
                negative_prompt="n",
            )

    class _FakeImages:
        def generate(self, prompt: str) -> ImageResult:
            return ImageResult(prompt=prompt, url="https://example.com/x.png")

    class _FakeStorage:
        def upload(self, data: bytes, *, content_type: str = "image/png") -> str:
            return "https://example.com/u.png"

    bus = EventBus()
    pipeline = DirectorPipeline(
        image_generator=_FakeImages(),
        storage_client=_FakeStorage(),
        domain_service=_FakeDomainService(),  # type: ignore[arg-type]
        event_bus=bus,
        max_storyboard_retries=0,
    )
    pipeline._research_agent = _FakeResearch()  # type: ignore[assignment]
    pipeline._director_agent = _FakeDirector()  # type: ignore[assignment]
    pipeline._prompt_agent = _FakePrompt()  # type: ignore[assignment]
    pipeline._review_agent = _FakeReview()  # type: ignore[assignment]

    # Classic path unchanged
    result = pipeline.generate("Orchestration BC topic")
    assert result.storyboard.topic == "Orchestration BC topic"

    # Orchestrated path (additive)
    pipeline.orchestrator._store = OrchestrationStore(root=tmp_path)
    graph = pipeline.run_orchestrated(
        "Orchestration BC topic",
        auto_approve_checkpoints=True,
        checkpoint_after_director=False,
        checkpoint_after_review=False,
    )
    assert graph.status == GraphStatus.SUCCESS
    assert graph.outputs["review"]["approved"] is True

    reload_settings()
