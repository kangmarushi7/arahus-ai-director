"""Unit tests for domain-aware pipeline integration."""

from __future__ import annotations

from typing import Any, Type, TypeVar

import pytest
from pydantic import BaseModel

from src.agents.prompt import PromptAgent, SceneContentPlan, generate_prompt_agent_prompt
from src.agents.research import generate_research_prompt
from src.agents.director import generate_director_prompt
from src.domain import (
    ConfigLoader,
    DomainDetector,
    DomainInfo,
    DomainRegistry,
    DomainService,
    DomainType,
)
from src.models.context import PipelineContext
from src.models.image import ImageResult
from src.models.research import ResearchResult
from src.models.review import ReviewResult
from src.models.storyboard import DirectorPlan, Scene, Storyboard
from src.pipeline import DirectorPipeline
from src.prompt import PromptComposer

T = TypeVar("T", bound=BaseModel)


class _FixedDomainDetector(DomainDetector):
    def __init__(self, domain: DomainType, *, confidence: float = 0.95) -> None:
        self._domain = domain
        self._confidence = confidence

    def detect(self, topic: str) -> DomainInfo:
        return DomainInfo(
            domain=self._domain,
            confidence=self._confidence,
            reasoning=f"fixed detector for {self._domain.value}",
            keywords=[self._domain.value, topic.split()[0].lower()],
            suggested_style="",
            suggested_camera="",
            suggested_negative_prompt="",
        )


class _FakeLLM:
    """Minimal LLM stub that returns pre-seeded Pydantic models by type."""

    def __init__(self, responses: dict[type[BaseModel], BaseModel]) -> None:
        self._responses = responses
        self.progress_callback = None
        self.calls: list[type[BaseModel]] = []

    def generate_json(self, prompt: str, response_model: Type[T]) -> T:
        self.calls.append(response_model)
        if "Detected domain context" in prompt or "Detected DomainInfo" in prompt:
            assert "domain:" in prompt
        value = self._responses[response_model]
        assert isinstance(value, response_model)
        return value


class _StubImageGen:
    def generate(self, prompt: str) -> ImageResult:
        return ImageResult(prompt=prompt, url="https://example.test/img.png")


class _StubStorage:
    def upload(self, data: bytes, *, content_type: str = "image/png") -> str:
        return "https://example.test/upload.png"


def _sample_research(topic: str) -> ResearchResult:
    return ResearchResult(
        topic=topic,
        time_period="test era",
        location="test location",
        key_people=["Person A"],
        visual_details=["detail one"],
    )


def _sample_plan(topic: str) -> DirectorPlan:
    return DirectorPlan(
        topic=topic,
        scenes=[
            Scene(id=1, title="One", description="First scene description " * 8),
            Scene(id=2, title="Two", description="Second scene description " * 8),
            Scene(id=3, title="Three", description="Third scene description " * 8),
            Scene(id=4, title="Four", description="Fourth scene description " * 8),
        ],
    )


def _sample_content(topic: str) -> SceneContentPlan:
    return SceneContentPlan(
        topic=topic,
        scenes=[
            {
                "id": 1,
                "title": "One",
                "description": "First scene description " * 8,
                "subject": "primary subject one",
                "environment": "environment one",
                "action": "action one",
            },
            {
                "id": 2,
                "title": "Two",
                "description": "Second scene description " * 8,
                "subject": "primary subject two",
                "environment": "environment two",
                "action": "action two",
            },
            {
                "id": 3,
                "title": "Three",
                "description": "Third scene description " * 8,
                "subject": "primary subject three",
                "environment": "environment three",
                "action": "action three",
            },
            {
                "id": 4,
                "title": "Four",
                "description": "Fourth scene description " * 8,
                "subject": "primary subject four",
                "environment": "environment four",
                "action": "action four",
            },
        ],
    )


def _sample_review() -> ReviewResult:
    return ReviewResult(
        overall_score=92,
        domain_accuracy=90,
        visual_quality=90,
        scene_continuity=90,
        prompt_quality=90,
        approved=True,
        issues=[],
        recommendations=[],
    )


def _build_domain_service(domain: DomainType) -> DomainService:
    return DomainService(
        detector=_FixedDomainDetector(domain),
        registry=DomainRegistry(),
        config_loader=ConfigLoader(),
        enrich_from_registry=True,
    )


@pytest.mark.parametrize(
    ("topic", "expected_domain"),
    [
        ("The Fall of Constantinople", DomainType.HISTORY),
        ("Bitcoin ETF", DomainType.FINANCE),
        ("Life on Mars in 2150", DomainType.SCIFI),
    ],
)
def test_pipeline_domain_topics(
    topic: str,
    expected_domain: DomainType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Keep PromptAgent composition deterministic for domain assertions.
    monkeypatch.setenv("PROMPT_OPTIMIZER_ENABLED", "false")
    monkeypatch.setenv("PERSIST_PIPELINE_RUNS", "false")
    from src.config import get_settings

    get_settings.cache_clear()

    research = _sample_research(topic)
    plan = _sample_plan(topic)
    content = _sample_content(topic)
    review = _sample_review()

    llm = _FakeLLM(
        {
            ResearchResult: research,
            DirectorPlan: plan,
            SceneContentPlan: content,
            ReviewResult: review,
        }
    )
    domain_service = _build_domain_service(expected_domain)
    pipeline = DirectorPipeline(
        image_generator=_StubImageGen(),
        storage_client=_StubStorage(),
        research_llm=llm,  # type: ignore[arg-type]
        director_llm=llm,  # type: ignore[arg-type]
        prompt_llm=llm,  # type: ignore[arg-type]
        review_llm=llm,  # type: ignore[arg-type]
        domain_service=domain_service,
        prompt_composer=PromptComposer(),
        max_storyboard_retries=0,
    )

    result = pipeline.generate(topic)

    assert result.domain_info is not None
    assert result.domain_info.domain == expected_domain
    assert result.prompt_context is not None
    assert result.prompt_context.domain == expected_domain
    assert result.context is not None
    assert isinstance(result.context, PipelineContext)
    assert result.context.domain_info.domain == expected_domain

    # Domain YAML style/camera must appear in composed prompts.
    style_token = result.prompt_context.style.split(",")[0].strip()
    camera_token = result.prompt_context.camera.split(",")[0].strip()
    for scene in result.storyboard.scenes:
        assert scene.image_prompt
        assert "primary subject" in scene.image_prompt
        assert style_token in scene.image_prompt
        assert camera_token in scene.image_prompt

    assert result.metrics.get("domain_seconds", 0) >= 0
    assert result.using_stub_services is False
    get_settings.cache_clear()


def test_prompt_agent_uses_composer_not_manual_suffix() -> None:
    topic = "Bitcoin ETF"
    domain = DomainType.FINANCE
    prompt_context = ConfigLoader().load(domain)
    domain_info = DomainInfo(
        domain=domain,
        confidence=0.9,
        reasoning="finance topic",
        keywords=["bitcoin", "etf"],
    )
    plan = _sample_plan(topic)
    research = _sample_research(topic)
    content = _sample_content(topic)
    llm = _FakeLLM({SceneContentPlan: content})

    agent = PromptAgent(
        llm,  # type: ignore[arg-type]
        prompt_composer=PromptComposer(),
        config_loader=ConfigLoader(),
    )
    storyboard = agent.run(
        plan,
        research,
        domain_info=domain_info,
        prompt_context=prompt_context,
    )

    assert isinstance(storyboard, Storyboard)
    prompt = storyboard.scenes[0].image_prompt or ""
    assert "primary subject one" in prompt
    assert prompt_context.style.split(",")[0].strip() in prompt
    # Legacy hardcoded historical suffix must not be forced.
    assert "photorealistic historical drama" not in prompt


def test_agent_prompts_include_domain_info() -> None:
    info = DomainInfo(
        domain=DomainType.SCIFI,
        confidence=0.91,
        reasoning="future colony",
        keywords=["mars", "colony"],
        suggested_style="futuristic",
        suggested_camera="anamorphic",
    )
    research = _sample_research("Life on Mars in 2150")
    plan = _sample_plan("Life on Mars in 2150")
    ctx = ConfigLoader().load(DomainType.SCIFI)

    research_prompt = generate_research_prompt("Life on Mars in 2150", info)
    director_prompt = generate_director_prompt("Life on Mars in 2150", research, info)
    prompt_prompt = generate_prompt_agent_prompt(plan, research, info, ctx)

    assert "scifi" in research_prompt
    assert "future colony" in research_prompt
    assert "scifi" in director_prompt
    assert "DomainInfo" in director_prompt
    assert "subject" in prompt_prompt
    assert "PromptComposer" in prompt_prompt or "composition engine" in prompt_prompt
