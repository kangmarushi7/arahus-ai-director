"""Orchestration smoke tests with fakes (no live LLM/RunPod)."""

from __future__ import annotations

from src.domain.models import DomainInfo, DomainType
from src.domain.prompt_context import DomainPromptContext
from src.events import EventBus, ResearchCompleted
from src.models.image import ImageResult
from src.models.research import ResearchResult
from src.models.review import ReviewResult
from src.models.storyboard import DirectorPlan, Scene, Storyboard
from src.pipeline import DirectorPipeline


class _FakeDomainService:
    def detect(self, topic: str) -> DomainInfo:
        return DomainInfo(
            domain=DomainType.GENERAL,
            confidence=0.9,
            reasoning="test",
        )

    def get_prompt_context(self, domain: DomainType) -> DomainPromptContext:
        return DomainPromptContext(
            domain=domain,
            style="test style",
            camera="test camera",
            lighting="test light",
            color_palette="test palette",
            composition="test composition",
            quality_tags=["detailed"],
            negative_prompt="blurry",
        )


class _FakeResearch:
    def run(self, topic: str, domain_info=None):
        return ResearchResult(
            topic=topic,
            time_period="now",
            location="lab",
            key_people=["Ada Lovelace"],
            historical_notes=["test research"],
        )


class _FakeDirector:
    def run(self, topic: str, research, domain_info=None, character_bible: str = ""):
        scenes = [
            Scene(id=i, title=f"S{i}", description=f"Ada Lovelace in scene {i}")
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
                image_prompt=f"prompt for {s.title}",
            )
            for s in plan.scenes
        ]
        return Storyboard(topic=plan.topic, scenes=scenes)


class _FakeReview:
    def run(self, storyboard, domain_info=None):
        return ReviewResult(
            overall_score=90,
            domain_accuracy=90,
            visual_quality=90,
            scene_continuity=90,
            prompt_quality=90,
            approved=True,
        )


class _FakeImages:
    def generate(self, prompt: str) -> ImageResult:
        return ImageResult(prompt=prompt, url="https://example.com/x.png")


class _FakeStorage:
    def upload(self, data: bytes, *, content_type: str = "image/png") -> str:
        return "https://example.com/uploaded.png"


def test_pipeline_publishes_research_event(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_STUB_SERVICES", "true")
    monkeypatch.setenv("PROMPT_OPTIMIZER_ENABLED", "false")
    monkeypatch.setenv("PERSIST_PIPELINE_RUNS", "false")
    from src.config import reload_settings

    reload_settings()

    bus = EventBus()
    seen: list[ResearchCompleted] = []
    bus.subscribe(ResearchCompleted, seen.append)

    pipeline = DirectorPipeline(
        image_generator=_FakeImages(),
        storage_client=_FakeStorage(),
        domain_service=_FakeDomainService(),  # type: ignore[arg-type]
        event_bus=bus,
        using_stub_services=False,
        max_storyboard_retries=0,
    )
    pipeline._research_agent = _FakeResearch()  # type: ignore[assignment]
    pipeline._director_agent = _FakeDirector()  # type: ignore[assignment]
    pipeline._prompt_agent = _FakePrompt()  # type: ignore[assignment]
    pipeline._review_agent = _FakeReview()  # type: ignore[assignment]

    result = pipeline.generate("Ada Lovelace computing")
    assert result.storyboard.topic == "Ada Lovelace computing"
    assert "Ada Lovelace" in result.character_bible
    assert seen and seen[0].topic == "Ada Lovelace computing"
    assert len(result.images) == 4
    reload_settings()
