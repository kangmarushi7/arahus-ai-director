"""StoryPlanner — cinematic planning engine for Director AI v2."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.models.scene_plan import ScenePlan, StoryPlan
from src.domain.models import DomainInfo
from src.models.research import ResearchResult
from src.services.llm import LLMClientError

if TYPE_CHECKING:
    from src.services.llm import LLMClient

logger = logging.getLogger(__name__)

SCENE_COUNT = 4

STORY_PLANNER_PROMPT_TEMPLATE = """You are an award-winning film director and \
cinematographer. Your job is cinematic PLANNING — not writing image prompts.

Topic: {topic}
{domain_block}
Verified research (authoritative — do not invent beyond it):
{research_block}

Create exactly {scene_count} ScenePlans that tell this story visually.

Rules:
1. Output structured cinematic plans, NOT finished image-generation prompts.
2. Generate exactly {scene_count} scenes — no more, no fewer.
3. Do not hallucinate people, places, objects, or events that conflict with research.
4. Each scene must advance to a distinct moment (no near-duplicates).
5. Fill cinematic fields with concrete, production-ready language:
   - camera_shot (e.g. wide establishing, medium close-up, over-the-shoulder)
   - camera_movement (e.g. slow push-in, static, tracking left)
   - camera_angle (e.g. eye-level, low angle, high angle, dutch)
   - lens (e.g. 35mm anamorphic, 85mm portrait, 24mm wide)
   - lighting (motivated, practical, time-of-day, quality)
   - composition (framing, leading lines, depth layers)
   - emotion (audience feeling / dramatic tone)
   - continuity (how this scene connects from the previous one — short prose)
   - continuity_meta (structured): previous_scene, keep[], change[]
   - negative_prompt (artifacts / style flaws to avoid — short)
6. Also provide subject, environment, and action as concise visual beats.
7. description is the visual narrative of what appears in frame (60–120 words).
8. Number scenes with contiguous ids 1..{scene_count}.
9. Enforce visual continuity: same clothing, hairstyle, weapons, architecture,
   and color identity unless explicitly listed under continuity_meta.change.
10. Return ONLY valid JSON. No markdown. No explanation.

Schema:

{{
  "topic": "{topic}",
  "scenes": [
    {{
      "id": 1,
      "title": "...",
      "description": "...",
      "subject": "...",
      "environment": "...",
      "action": "...",
      "camera_shot": "...",
      "camera_movement": "...",
      "camera_angle": "...",
      "lens": "...",
      "lighting": "...",
      "composition": "...",
      "emotion": "...",
      "continuity": "...",
      "continuity_meta": {{
        "previous_scene": "",
        "keep": ["character", "costume", "lighting", "location"],
        "change": ["emotion", "camera"]
      }},
      "negative_prompt": "..."
    }}
  ]
}}

Return only JSON."""


class StoryPlannerError(Exception):
    """Raised when story planning fails."""

    def __init__(self, message: str, *, topic: str | None = None) -> None:
        super().__init__(message)
        self.topic = topic


def _format_research_block(research: ResearchResult) -> str:
    sections = {
        "Topic": research.topic,
        "Time period": research.time_period,
        "Location": research.location,
        "Key people": ", ".join(research.key_people),
        "Key locations": ", ".join(research.key_locations),
        "Architecture": ", ".join(research.architecture),
        "Weapons": ", ".join(research.weapons),
        "Clothing": ", ".join(research.clothing),
        "Important events": ", ".join(research.important_events),
        "Visual details": ", ".join(research.visual_details),
        "Historical notes": ", ".join(research.historical_notes),
    }
    lines = [f"- {label}: {value}" for label, value in sections.items() if value]
    if not lines:
        return "- (no additional structured research fields were provided)"
    return "\n".join(lines)


def _format_domain_block(domain_info: DomainInfo | None) -> str:
    if domain_info is None:
        return ""
    keywords = ", ".join(domain_info.keywords) if domain_info.keywords else "(none)"
    return (
        "\nDetected DomainInfo (adapt cinematic language to this domain):\n"
        f"- domain: {domain_info.domain.value}\n"
        f"- confidence: {domain_info.confidence:.3f}\n"
        f"- reasoning: {domain_info.reasoning}\n"
        f"- keywords: {keywords}\n"
        f"- suggested_style: {domain_info.suggested_style or '(none)'}\n"
        f"- suggested_camera: {domain_info.suggested_camera or '(none)'}\n"
    )


def generate_story_planner_prompt(
    topic: str,
    research: ResearchResult,
    domain_info: DomainInfo | None = None,
    character_bible: str = "",
) -> str:
    """Build the StoryPlanner LLM instruction."""
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("topic must be a non-empty string")
    if not isinstance(research, ResearchResult):
        raise ValueError("research must be a ResearchResult instance")

    prompt = STORY_PLANNER_PROMPT_TEMPLATE.format(
        topic=" ".join(topic.split()),
        domain_block=_format_domain_block(domain_info),
        research_block=_format_research_block(research),
        scene_count=SCENE_COUNT,
    )
    bible = character_bible.strip()
    if bible:
        prompt = f"{prompt}\n\n{bible}\n"
    return prompt


def validate_story_plan(plan: StoryPlan, *, topic: str) -> StoryPlan:
    """Enforce cinematic planning invariants beyond Pydantic shape checks."""
    if len(plan.scenes) != SCENE_COUNT:
        raise StoryPlannerError(
            f"StoryPlan must contain exactly {SCENE_COUNT} scenes, "
            f"got {len(plan.scenes)}",
            topic=topic,
        )

    titles: list[str] = []
    for index, scene in enumerate(plan.scenes, start=1):
        if scene.id != index:
            raise StoryPlannerError(
                f"ScenePlan ids must be contiguous 1..{SCENE_COUNT}; "
                f"expected id={index}, got id={scene.id}",
                topic=topic,
            )
        if not scene.title.strip():
            raise StoryPlannerError(f"Scene {index} is missing a title", topic=topic)
        if not scene.description.strip():
            raise StoryPlannerError(
                f"Scene {index} is missing a description",
                topic=topic,
            )
        normalized = " ".join(scene.title.lower().split())
        if normalized in titles:
            raise StoryPlannerError(
                f"Duplicate scene title detected: {scene.title!r}",
                topic=topic,
            )
        titles.append(normalized)
    return plan


class StoryPlanner:
    """Cinematic planning engine that outputs :class:`StoryPlan` / ScenePlans.

    This is the Director AI v2 core. It does not write final image prompts —
    that remains :class:`~src.prompt.composer.PromptComposer`'s job.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        if llm_client is None:
            raise ValueError("llm_client is required")
        self._llm = llm_client
        self.logger = logging.getLogger(self.__class__.__name__)

    def plan(
        self,
        topic: str,
        research: ResearchResult,
        domain_info: DomainInfo | None = None,
        character_bible: str = "",
    ) -> StoryPlan:
        """Plan exactly four cinematic :class:`ScenePlan` rows for ``topic``."""
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("topic must be a non-empty string")
        if not isinstance(research, ResearchResult):
            raise ValueError("research must be a ResearchResult instance")

        cleaned = " ".join(topic.split())
        prompt = generate_story_planner_prompt(
            cleaned,
            research,
            domain_info,
            character_bible=character_bible,
        )
        self.logger.info(
            "event=story_planner_start topic=%r domain=%s",
            cleaned,
            domain_info.domain.value if domain_info else None,
        )
        try:
            plan = self._llm.generate_json(prompt, StoryPlan)
        except LLMClientError as exc:
            raise StoryPlannerError(
                f"Failed to plan story for {cleaned!r}: {exc}",
                topic=cleaned,
            ) from exc

        if not isinstance(plan, StoryPlan):
            raise StoryPlannerError(
                f"LLM returned non-StoryPlan ({type(plan).__name__})",
                topic=cleaned,
            )

        validated = validate_story_plan(plan, topic=cleaned)
        # Prefer caller topic when the model echoes a variant.
        if validated.topic.strip() != cleaned:
            validated = validated.model_copy(update={"topic": cleaned})
        linked = validated.with_continuity_links()
        self.logger.info(
            "event=story_planner_complete topic=%r scenes=%s",
            linked.topic,
            len(linked.scenes),
        )
        return linked
