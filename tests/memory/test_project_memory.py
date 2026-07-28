"""Unit tests for Character & World Memory (Sprint 5.2)."""

from __future__ import annotations

from pathlib import Path

from src.domain.models import DomainInfo, DomainType
from src.domain.prompt_context import DomainPromptContext
from src.memory import (
    AssetKind,
    CharacterBible,
    ProjectMemory,
    ProjectMemoryStore,
    SceneContinuityMeta,
    StyleBible,
    WorldBuilder,
    WorldBible,
    build_memory_packs,
    project_id_for_topic,
    slugify,
)
from src.models.memory import AppearanceBible, LocationBible, UniformBible
from src.models.research import ResearchResult
from src.models.scene_plan import ScenePlan, StoryPlan
from src.prompt.composer import PromptComposer


def _sample_research(topic: str = "Napoleon crossing the Alps") -> ResearchResult:
    return ResearchResult(
        topic=topic,
        time_period="1800",
        location="Great St Bernard Pass",
        key_people=["Napoleon Bonaparte"],
        key_locations=["Great St Bernard Pass", "Alpine ridge"],
        architecture=["mountain hospice", "snowbound trail"],
        clothing=["blue military coat", "bicorne"],
        weapons=["cavalry saber"],
        visual_details=["white horse", "snow glare"],
    )


def _sample_domain() -> DomainPromptContext:
    return DomainPromptContext(
        domain=DomainType.HISTORY,
        style="cinematic historical drama",
        camera="35mm anamorphic",
        lighting="dramatic alpine light",
        composition="heroic low angle",
        color_palette="cold blues, warm coat accents",
        quality_tags=["highly detailed", "sharp focus"],
        negative_prompt="blurry, watermark",
    )


class TestIdsAndSerialization:
    def test_slugify_and_project_id_stable(self) -> None:
        assert slugify("Napoleon Bonaparte") == "napoleon_bonaparte"
        a = project_id_for_topic("Napoleon crossing the Alps")
        b = project_id_for_topic("Napoleon crossing the Alps")
        assert a == b
        assert "napoleon" in a

    def test_character_bible_round_trip(self) -> None:
        character = CharacterBible(
            id="napoleon",
            asset_id=17,
            name="Napoleon Bonaparte",
            appearance=AppearanceBible(
                age="35",
                height="168 cm",
                body="lean military",
                uniform=UniformBible(primary="blue military coat", hat="bicorne"),
                horse="white",
            ),
            personality="confident",
            voice="deep",
            negative=["beard", "modern clothes"],
        )
        payload = character.to_dict()
        restored = CharacterBible.model_validate(payload)
        assert restored.asset_id == 17
        assert "blue military coat" in restored.to_prompt_fragment()
        assert "Character #17" in restored.to_prompt_fragment()

    def test_project_memory_json_round_trip(self) -> None:
        memory = ProjectMemory(
            project_id="demo_project",
            topic="Demo",
            characters=[
                CharacterBible(
                    id="napoleon",
                    asset_id=1,
                    name="Napoleon",
                    appearance=AppearanceBible(
                        uniform=UniformBible(primary="blue coat")
                    ),
                )
            ],
            world=WorldBible(
                locations=[
                    LocationBible(
                        id="alps",
                        asset_id=2,
                        name="Alps",
                        weather="snow",
                        architecture="mountain pass",
                        time="1800",
                        lighting="golden hour",
                    )
                ],
                primary_location_id="alps",
                era="1800",
            ),
            style=StyleBible(
                visual_style="cinematic realism",
                camera="ARRI Alexa",
                lighting="dramatic",
                color_palette="teal orange",
                quality="ultra detailed",
                asset_id=3,
            ),
        )
        restored = ProjectMemory.from_dict(memory.to_dict())
        assert restored.characters[0].name == "Napoleon"
        assert restored.world.primary_location().name == "Alps"
        assert restored.style.color_palette == "teal orange"
        assert restored.registry is not None


class TestAssetRegistryAndStore:
    def test_registry_assigns_stable_ids(self, tmp_path: Path) -> None:
        store = ProjectMemoryStore(root=tmp_path)
        builder = WorldBuilder(store=store)
        memory = builder.build(_sample_research(), prompt_context=_sample_domain())
        assert memory.registry is not None
        napoleon = memory.find_character("Napoleon Bonaparte")
        assert napoleon is not None
        first_id = napoleon.asset_id

        # Rebuild for same topic — IDs stay stable.
        again = builder.build(_sample_research(), prompt_context=_sample_domain())
        again_char = again.find_character("Napoleon Bonaparte")
        assert again_char is not None
        assert again_char.asset_id == first_id
        style = again.registry.get_by_slug("project_style")
        assert style is not None
        assert style.kind == AssetKind.STYLE

    def test_store_persists_and_reloads(self, tmp_path: Path) -> None:
        store = ProjectMemoryStore(root=tmp_path)
        memory = WorldBuilder(store=store).build(
            _sample_research(),
            prompt_context=_sample_domain(),
            persist=True,
        )
        loaded = store.load(memory.project_id)
        assert loaded is not None
        assert loaded.characters[0].name == "Napoleon Bonaparte"
        assert loaded.world.locations
        assert loaded.style.visual_style


class TestWorldBuilder:
    def test_builds_character_world_style_from_research(self, tmp_path: Path) -> None:
        builder = WorldBuilder(store=ProjectMemoryStore(root=tmp_path))
        info = DomainInfo(
            domain=DomainType.HISTORY,
            confidence=0.9,
            reasoning="historical campaign",
            keywords=["napoleon", "alps"],
            suggested_style="historical epic",
            suggested_camera="anamorphic",
        )
        memory = builder.build(
            _sample_research(),
            domain_info=info,
            prompt_context=_sample_domain(),
        )
        assert len(memory.characters) == 1
        assert "blue military" in memory.characters[0].appearance.uniform.primary
        assert memory.world.era == "1800"
        assert memory.style.camera
        bible = memory.character_bible_text()
        assert "Napoleon Bonaparte" in bible
        assert "#" in bible


class TestSceneContinuityMeta:
    def test_story_plan_fills_continuity_links(self) -> None:
        scenes = [
            ScenePlan(
                id=i,
                title=f"Scene {i}",
                description="A visual beat with enough narrative detail " * 4,
                continuity="links forward",
            )
            for i in range(1, 5)
        ]
        plan = StoryPlan(topic="Alps", scenes=scenes).with_continuity_links()
        assert plan.scenes[0].continuity_meta is not None
        assert plan.scenes[0].continuity_meta.previous_scene == ""
        assert "character" in plan.scenes[0].continuity_meta.keep
        assert plan.scenes[1].continuity_meta.previous_scene == "scene_1"
        assert "emotion" in plan.scenes[1].continuity_meta.change

    def test_continuity_meta_serialization(self) -> None:
        meta = SceneContinuityMeta(
            previous_scene=4,
            keep=["character", "costume"],
            change=["camera"],
        )
        assert meta.previous_scene == "scene_4"
        payload = meta.to_dict()
        restored = SceneContinuityMeta.model_validate(payload)
        assert restored.keep == ["character", "costume"]


class TestPromptComposerMemoryInjection:
    def test_compose_injects_character_world_style(self, tmp_path: Path) -> None:
        memory = WorldBuilder(store=ProjectMemoryStore(root=tmp_path)).build(
            _sample_research(),
            prompt_context=_sample_domain(),
        )
        scene = ScenePlan(
            id=2,
            title="Crossing",
            description="Napoleon leads the column over the pass at dawn " * 3,
            subject="Napoleon on horseback",
            environment="snowy alpine pass",
            action="army advances",
            camera_shot="wide",
            camera_angle="low angle",
            lens="35mm",
            camera_movement="static",
            lighting="dawn backlight",
            composition="leading lines",
            emotion="resolve",
            continuity="continues the ascent",
            continuity_meta=SceneContinuityMeta(
                previous_scene="scene_1",
                keep=["character", "costume", "horse"],
                change=["camera", "emotion"],
            ),
            negative_prompt="cartoon",
        )
        packs = build_memory_packs(memory, scene_plan=scene)
        assert [pack.name for pack in packs] == [
            "character_bible",
            "world_bible",
            "style_bible",
            "scene_continuity",
        ]

        final = PromptComposer().compose_from_scene_plan(
            scene,
            _sample_domain(),
            project_memory=memory,
        )
        positive = final.positive_prompt
        assert "Napoleon" in positive
        assert "Character #" in positive
        assert "Location #" in positive or "Great St Bernard" in positive
        assert "keep character" in positive or "keep character, costume" in positive
        assert "cinematic" in positive.casefold() or memory.style.visual_style in positive
        assert "character_bible" in final.metadata["packs_applied"]
        assert "world_bible" in final.metadata["packs_applied"]
        assert "style_bible" in final.metadata["packs_applied"]
        assert "modern clothing" in final.negative_prompt.casefold() or "beard" in (
            ",".join(memory.characters[0].negative)
        )

    def test_compose_without_memory_still_works(self) -> None:
        scene = ScenePlan(
            id=1,
            title="Solo",
            description="A lone rider cresting a snow ridge under cold light " * 3,
            subject="rider",
            environment="ridge",
            action="cresting",
            camera_shot="medium",
        )
        final = PromptComposer().compose_from_scene_plan(scene, _sample_domain())
        assert "rider" in final.positive_prompt
        assert "character_bible" not in final.metadata.get("packs_applied", [])
