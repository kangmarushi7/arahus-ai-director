"""Default creative workflow — wraps existing agents without changing them."""

from __future__ import annotations

from typing import Any, Callable

from src.models.base import StrictModel
from src.models.research import ResearchResult
from src.models.review import ReviewResult
from src.models.storyboard import DirectorPlan, Storyboard
from src.orchestration.models import AgentNodeSpec
from src.orchestration.orchestrator import AgentOrchestrator, AgentRunner


def creative_workflow_specs(
    *,
    checkpoint_after_research: bool = False,
    checkpoint_after_director: bool = True,
    checkpoint_after_review: bool = True,
) -> list[AgentNodeSpec]:
    """DAG: research → director → prompt ∥ (optional) → review.

    Prompt depends on director; review depends on prompt. Research and director
    are sequential. Prompt is parallel_safe for future fan-out nodes.
    """
    return [
        AgentNodeSpec(
            id="research",
            agent_name="research",
            depends_on=[],
            max_retries=2,
            checkpoint=checkpoint_after_research,
            cost_estimate_usd=0.02,
            description="Domain research",
        ),
        AgentNodeSpec(
            id="director",
            agent_name="director",
            depends_on=["research"],
            max_retries=2,
            checkpoint=checkpoint_after_director,
            cost_estimate_usd=0.03,
            description="Scene planning",
        ),
        AgentNodeSpec(
            id="prompt",
            agent_name="prompt",
            depends_on=["director"],
            max_retries=2,
            parallel_safe=True,
            cost_estimate_usd=0.04,
            description="Storyboard prompts",
        ),
        AgentNodeSpec(
            id="review",
            agent_name="review",
            depends_on=["prompt"],
            max_retries=1,
            checkpoint=checkpoint_after_review,
            cost_estimate_usd=0.02,
            description="Quality review",
        ),
    ]


def parallel_demo_specs() -> list[AgentNodeSpec]:
    """Small parallel DAG for tests: a → (b ∥ c) → d."""
    return [
        AgentNodeSpec(id="a", agent_name="a", depends_on=[], cost_estimate_usd=0.01),
        AgentNodeSpec(
            id="b",
            agent_name="b",
            depends_on=["a"],
            parallel_safe=True,
            cost_estimate_usd=0.01,
        ),
        AgentNodeSpec(
            id="c",
            agent_name="c",
            depends_on=["a"],
            parallel_safe=True,
            cost_estimate_usd=0.01,
        ),
        AgentNodeSpec(
            id="d",
            agent_name="d",
            depends_on=["b", "c"],
            cost_estimate_usd=0.01,
        ),
    ]


def _as_payload(model: StrictModel) -> StrictModel:
    return model


def bind_research_runner(agent: Any) -> AgentRunner:
    def run(
        *,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        node_id: str,
        run_id: str,
    ) -> ResearchResult:
        result = agent.run(
            inputs["topic"],
            domain_info=inputs.get("domain_info"),
        )
        if not isinstance(result, ResearchResult):
            raise TypeError("ResearchAgent must return ResearchResult")
        return _as_payload(result)

    return run


def bind_director_runner(agent: Any) -> AgentRunner:
    def run(
        *,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        node_id: str,
        run_id: str,
    ) -> DirectorPlan:
        research_payload = outputs.get("research") or {}
        research = ResearchResult.model_validate(research_payload)
        result = agent.run(
            inputs["topic"],
            research,
            domain_info=inputs.get("domain_info"),
            character_bible=inputs.get("character_bible", ""),
        )
        if not isinstance(result, DirectorPlan):
            raise TypeError("DirectorAgent must return DirectorPlan")
        return _as_payload(result)

    return run


def bind_prompt_runner(agent: Any) -> AgentRunner:
    def run(
        *,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        node_id: str,
        run_id: str,
    ) -> Storyboard:
        plan = DirectorPlan.model_validate(outputs.get("director") or {})
        research = ResearchResult.model_validate(outputs.get("research") or {})
        result = agent.run(
            plan,
            research,
            domain_info=inputs.get("domain_info"),
            prompt_context=inputs.get("prompt_context"),
            character_bible=inputs.get("character_bible", ""),
            project_memory=inputs.get("project_memory"),
        )
        if not isinstance(result, Storyboard):
            raise TypeError("PromptAgent must return Storyboard")
        return _as_payload(result)

    return run


def bind_review_runner(agent: Any) -> AgentRunner:
    def run(
        *,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        node_id: str,
        run_id: str,
    ) -> ReviewResult:
        storyboard = Storyboard.model_validate(outputs.get("prompt") or {})
        result = agent.run(
            storyboard,
            domain_info=inputs.get("domain_info"),
        )
        if not isinstance(result, ReviewResult):
            raise TypeError("ReviewAgent must return ReviewResult")
        return _as_payload(result)

    return run


def wire_creative_agents(
    orchestrator: AgentOrchestrator,
    *,
    research_agent: Any,
    director_agent: Any,
    prompt_agent: Any,
    review_agent: Any,
) -> AgentOrchestrator:
    """Register runners that call existing agents — no agent code changes."""
    orchestrator.register_runner("research", bind_research_runner(research_agent))
    orchestrator.register_runner("director", bind_director_runner(director_agent))
    orchestrator.register_runner("prompt", bind_prompt_runner(prompt_agent))
    orchestrator.register_runner("review", bind_review_runner(review_agent))
    return orchestrator


def make_echo_runner(
    name: str,
    payload_fn: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
) -> AgentRunner:
    """Test helper runner returning a structured dict payload."""

    def run(
        *,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        node_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        if payload_fn:
            return payload_fn(inputs, outputs)
        return {"agent": name, "node_id": node_id, "echo": inputs.get("topic", "")}

    return run
