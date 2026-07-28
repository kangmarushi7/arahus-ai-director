"""Unit tests for Director AI v2 (StoryPlanner, ScenePlan, PromptComposer)."""

from __future__ import annotations

from typing import Type, TypeVar

import pytest
from pydantic import BaseModel, ValidationError

from src.agents.director import DirectorAgent, generate_director_prompt
from src.agents.prompt import PromptAgent
from src.director import (
    ScenePlan,
    StoryPlan,
    StoryPlanner,
    StoryPlannerError,
    generate_story_planner_prompt,
    validate_story_plan,
)
from src.domain import DomainInfo, DomainType
from src.domain.prompt_context import DomainPromptContext
from src.models.research import ResearchResult
from src.models.storyboard import DirectorPlan, Scene
from src.prompt.composer import PromptComposer

T = TypeVar("T", bound=BaseModel)


def _sample_research(topic: str = "The Fall of Constantinople") -> ResearchResult:
    return ResearchResult(
        topic=topic,
        time_period="1453",
        location="Constantinople",
        key_people=["Mehmed II", "Constantine XI"],
        visual_details=["Theodosian Walls", "Orban's cannon"],
    )


def _sample_scene_plan(scene_id: int = 1) -> ScenePlan:
    return ScenePlan(
        id=scene_id,
        title=f"Scene {scene_id}",
        description=(
            "Defenders man the battered Theodosian Walls at dawn while "
            "Ottoman artillery looms beyond the fosse, smoke drifting across "
            "the battlements in muted gold light."
        ),
        subject="Byzantine defenders on the walls",
        environment="Theodosian Walls, dawn, Constantinople 1453",
        action="soldiers brace for bombardment",
        camera_shot="wide establishing",
        camera_movement="slow push-in",
        camera_angle="low angle",
        lens="35mm anamorphic",
        lighting="motivated dawn backlight, soft haze",
        composition="layered depth, walls in foreground, camp beyond",
        emotion="tense resolve",
        continuity="opens the siege sequence after the overnight watch",
        negative_prompt="modern clothing, text overlay, cartoon",
    )


def _four_scene_plans() -> list[ScenePlan]:
    titles = ["Bombard", "Fleet", "Breach", "Last Stand"]
    plans: list[ScenePlan] = []
    for index, title in enumerate(titles, start=1):
        plan = _sample_scene_plan(index).model_copy(
            update={"title": title, "continuity": f"continues from beat {index - 1}"}
        )
        plans.append(plan)
    return plans


class _FakeLLM:
    def __init__(self, response: BaseModel) -> None:
        self._response = response
        self.calls: list[type[BaseModel]] = []
        self.progress_callback = None

    def generate_json(self, prompt: str, response_model: Type[T]) -> T:
        self.calls.append(response_model)
        assert "camera_shot" in prompt or "ScenePlans" in prompt or "cinematic" in prompt.lower()
        value = self._response
        assert isinstance(value, response_model)
        return value  # type: ignore[return-value]


class TestScenePlanSerialization:
    def test_round_trip_dict(self) -> None:
        plan = _sample_scene_plan()
        payload = plan.to_dict()
        restored = ScenePlan.model_validate(payload)
        assert restored.camera_shot == "wide establishing"
        assert restored.lens == "35mm anamorphic"
        assert restored.emotion == "tense resolve"
        assert restored.negative_prompt.startswith("modern clothing")

    def test_camera_directive_joins_fields(self) -> None:
        plan = _sample_scene_plan()
        directive = plan.camera_directive()
        assert "wide establishing" in directive
        assert "low angle" in directive
        assert "35mm anamorphic" in directive
        assert "slow push-in" in directive

    def test_story_plan_to_director_plan_preserves_scene_plans(self) -> None:
        story = StoryPlan(topic="Siege", scenes=_four_scene_plans())
        director = story.to_director_plan()
        assert isinstance(director, DirectorPlan)
        assert len(director.scenes) == 4
        assert director.scene_plans is not None
        assert len(director.scene_plans) == 4
        assert director.scenes[0].title == "Bombard"
        assert director.scene_plans[0].camera_shot == "wide establishing"

    def test_from_director_plan_legacy_without_scene_plans(self) -> None:
        legacy = DirectorPlan(
            topic="Siege",
            scenes=[
                Scene(id=i, title=f"T{i}", description=f"Description {i} " * 10)
                for i in range(1, 5)
            ],
        )
        story = StoryPlan.from_director_plan(legacy)
        assert len(story.scenes) == 4
        assert story.scenes[0].camera_shot == ""

    def test_invalid_ids_raise(self) -> None:
        scenes = _four_scene_plans()
        scenes[1] = scenes[1].model_copy(update={"id": 9})
        with pytest.raises(ValidationError):
            StoryPlan(topic="x", scenes=scenes)


class TestStoryPlanner:
    def test_plan_returns_validated_story_plan(self) -> None:
        story = StoryPlan(topic="The Fall of Constantinople", scenes=_four_scene_plans())
        llm = _FakeLLM(story)
        planner = StoryPlanner(llm)
        result = planner.plan(
            "The Fall of Constantinople",
            _sample_research(),
            DomainInfo(
                domain=DomainType.HISTORY,
                confidence=0.9,
                reasoning="historical siege",
                keywords=["ottoman", "byzantine"],
            ),
        )
        assert result.topic == "The Fall of Constantinople"
        assert len(result.scenes) == 4
        assert result.scenes[0].lighting
        assert llm.calls == [StoryPlan]

    def test_validate_rejects_duplicate_titles(self) -> None:
        scenes = _four_scene_plans()
        scenes[2] = scenes[2].model_copy(update={"title": "Bombard"})
        with pytest.raises(StoryPlannerError, match="Duplicate"):
            validate_story_plan(
                StoryPlan(topic="t", scenes=scenes),
                topic="t",
            )

    def test_prompt_includes_cinematic_fields(self) -> None:
        prompt = generate_story_planner_prompt(
            "Bitcoin ETF",
            _sample_research("Bitcoin ETF"),
        )
        for field in (
            "camera_shot",
            "camera_movement",
            "camera_angle",
            "lens",
            "lighting",
            "composition",
            "emotion",
            "continuity",
            "negative_prompt",
        ):
            assert field in prompt


class TestDirectorAgentV2:
    def test_run_returns_director_plan_with_scene_plans(self) -> None:
        story = StoryPlan(topic="Mars Colony", scenes=_four_scene_plans())
        # Align titles for uniqueness already in _four_scene_plans
        agent = DirectorAgent(_FakeLLM(story))
        plan = agent.run("Mars Colony", _sample_research("Mars Colony"))
        assert isinstance(plan, DirectorPlan)
        assert plan.scene_plans is not None
        assert len(plan.scene_plans) == 4
        assert plan.scenes[0].title == plan.scene_plans[0].title

    def test_generate_director_prompt_alias(self) -> None:
        prompt = generate_director_prompt("Topic", _sample_research("Topic"))
        assert "camera_shot" in prompt


class TestPromptComposerScenePlan:
    def test_compose_from_scene_plan_includes_cinematic_language(self) -> None:
        composer = PromptComposer()
        domain = DomainPromptContext(
            domain=DomainType.HISTORY,
            style="cinematic historical drama",
            camera="35mm documentary",
            lighting="natural period light",
            composition="balanced frame",
            color_palette="muted earth tones",
            quality_tags=["highly detailed"],
            negative_prompt="blurry, watermark",
        )
        final = composer.compose_from_scene_plan(_sample_scene_plan(), domain)
        assert "Byzantine defenders" in final.positive_prompt
        assert "35mm anamorphic" in final.positive_prompt
        assert "slow push-in" in final.positive_prompt
        assert "tense resolve" in final.positive_prompt
        assert "modern clothing" in final.negative_prompt
        assert final.metadata["source"] == "compose_from_scene_plan"
        assert final.metadata["camera_shot"] == "wide establishing"

    def test_compose_without_domain(self) -> None:
        final = PromptComposer().compose_from_scene_plan(_sample_scene_plan())
        assert "wide establishing" in final.positive_prompt
        assert final.negative_prompt


class TestPromptAgentScenePlansPath:
    def test_uses_composer_when_scene_plans_present(self) -> None:
        story = StoryPlan(topic="Siege", scenes=_four_scene_plans())
        plan = story.to_director_plan()
        llm = _FakeLLM(story)  # should not be called for content
        agent = PromptAgent(llm)
        board = agent.run(plan, _sample_research("Siege"))
        assert len(board.scenes) == 4
        assert board.scenes[0].image_prompt
        assert "35mm" in (board.scenes[0].image_prompt or "")
        assert llm.calls == []  # no SceneContentPlan LLM call
