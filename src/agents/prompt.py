"""Prompt agent: converts a director plan into SDXL-optimized image prompts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.agents.base import BaseAgent
from src.models.research import ResearchResult
from src.models.storyboard import DirectorPlan, Storyboard
from src.services.llm import LLMClientError

if TYPE_CHECKING:
    from src.services.llm import LLMClient

# Trailing style cues tuned for SDXL / SDXL-Turbo text-to-image models.
SDXL_STYLE_SUFFIX = (
    "cinematic still, photorealistic historical drama, ultra detailed, "
    "sharp focus, natural color grading, 35mm film look"
)

PROMPT_AGENT_TEMPLATE = """You are an expert SDXL prompt engineer for a historical \
film production.

Your only job is to write highly optimized text-to-image prompts. Do not generate \
images. Do not call tools. Do not invent upload steps.

Topic: {topic}

Director scenes (preserve id, title, and description exactly):
{scenes_block}

Verified research (use as authoritative visual reference):
{research_block}

For every scene, write one dense "image_prompt" optimized for SDXL.

Each image_prompt MUST explicitly include:
- architecture and built environment
- lighting (direction, quality, time of day)
- clothing and textiles
- weather and atmospheric conditions
- composition (subject placement, depth, framing — without camera jargon unless essential)
- materials and surface textures
- historical details grounded in the research (weapons, props, period markers)

Rules:
1. Keep every scene's "id", "title", and "description" exactly as given.
2. Produce exactly one image_prompt per scene, in the same order.
3. Describe only what should appear in the rendered image.
4. Do not write narration, dialogue, backstory, or modern anachronisms.
5. Prefer concrete nouns and visual adjectives over abstract emotion words.
6. Ground clothing, architecture, weapons, and materials in the verified research.
7. End every image_prompt with: {style}
8. Set "image" to null for every scene.
9. Return no markdown.
10. Return no explanation.
11. Return ONLY valid JSON.

Use exactly this schema:

{{
  "topic": "{topic}",
  "scenes": [
    {{
      "id": 1,
      "title": "...",
      "description": "...",
      "image_prompt": "...",
      "image": null
    }}
  ]
}}

Include every scene. Return only JSON."""


class PromptAgentError(Exception):
    """Raised when the prompt agent cannot produce a :class:`Storyboard`."""

    def __init__(self, message: str, *, topic: str | None = None) -> None:
        super().__init__(message)
        self.topic = topic


def _format_scenes_block(plan: DirectorPlan) -> str:
    """Render the plan's scenes as compact JSON for the prompt."""
    scenes = [
        {
            "id": scene.id,
            "title": scene.title,
            "description": scene.description,
        }
        for scene in plan.scenes
    ]
    return json.dumps(scenes, indent=2, ensure_ascii=False)


def _format_research_block(research: ResearchResult) -> str:
    """Render verified research as visual reference for SDXL prompts."""
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


def generate_prompt_agent_prompt(
    plan: DirectorPlan,
    research: ResearchResult,
) -> str:
    """Build the LLM prompt that turns a director plan into SDXL image prompts.

    Args:
        plan: The director's validated scene plan.
        research: Verified research for visual grounding.

    Returns:
        The prompt string to send to an LLM.

    Raises:
        ValueError: If ``plan`` or ``research`` has the wrong type.
    """
    if not isinstance(plan, DirectorPlan):
        raise ValueError("plan must be a DirectorPlan instance")
    if not isinstance(research, ResearchResult):
        raise ValueError("research must be a ResearchResult instance")

    return PROMPT_AGENT_TEMPLATE.format(
        topic=plan.topic,
        scenes_block=_format_scenes_block(plan),
        research_block=_format_research_block(research),
        style=SDXL_STYLE_SUFFIX,
    )


def _validate_storyboard(storyboard: Storyboard, plan: DirectorPlan) -> Storyboard:
    """Enforce prompt-agent invariants on the validated storyboard."""
    if len(storyboard.scenes) != len(plan.scenes):
        raise PromptAgentError(
            "Storyboard scene count must match the director plan: "
            f"expected {len(plan.scenes)}, got {len(storyboard.scenes)}",
            topic=plan.topic,
        )

    for expected, scene in zip(plan.scenes, storyboard.scenes, strict=True):
        if scene.id != expected.id:
            raise PromptAgentError(
                f"Storyboard scene id mismatch: expected {expected.id}, "
                f"got {scene.id}",
                topic=plan.topic,
            )
        if not scene.image_prompt or not scene.image_prompt.strip():
            raise PromptAgentError(
                f"Scene {scene.id} is missing an image_prompt",
                topic=plan.topic,
            )
        if scene.image is not None:
            raise PromptAgentError(
                f"Scene {scene.id} must not include a rendered image; "
                "PromptAgent only creates prompts",
                topic=plan.topic,
            )

    return storyboard


class PromptAgent(BaseAgent[Storyboard]):
    """Produces a validated :class:`Storyboard` of SDXL image prompts.

    This agent never calls RunPod and never uploads images. It only converts
    director scenes into text prompts via an injected LLM client.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
        debug: bool | None = None,
    ) -> None:
        """Store the injected LLM client.

        Args:
            llm_client: Client used to request validated JSON.
            max_retries: Forwarded to :class:`BaseAgent`.
            retry_backoff_seconds: Forwarded to :class:`BaseAgent`.
            debug: Forwarded to :class:`BaseAgent`.
        """
        super().__init__(
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            debug=debug,
        )
        self._llm_client = llm_client

    def run(self, plan: DirectorPlan, research: ResearchResult) -> Storyboard:
        """Convert each director scene into an SDXL-optimized image prompt.

        Workflow:
            1. Build a prompt-engineering instruction from ``plan`` + ``research``.
            2. Call ``llm_client.generate_json(..., Storyboard)``.
            3. Validate that every scene has an ``image_prompt`` and no image.
            4. Return the :class:`Storyboard`.

        Args:
            plan: The director's validated scene plan.
            research: Verified research used as visual context.

        Returns:
            The validated storyboard containing image prompts only.

        Raises:
            ValueError: If ``plan`` or ``research`` is invalid.
            PromptAgentError: If the LLM call or storyboard validation fails.
        """
        if not isinstance(plan, DirectorPlan):
            raise ValueError("plan must be a DirectorPlan instance")
        if not isinstance(research, ResearchResult):
            raise ValueError("research must be a ResearchResult instance")

        self.logger.info(
            "event=prompt_start agent=PromptAgent topic=%r scenes=%s",
            plan.topic,
            len(plan.scenes),
        )

        instruction = generate_prompt_agent_prompt(plan, research)
        if self.debug:
            self.logger.debug(
                "event=prompt_instruction_built agent=PromptAgent "
                "topic=%r prompt_chars=%s",
                plan.topic,
                len(instruction),
            )

        try:
            storyboard = self._execute(
                lambda: self._llm_client.generate_json(instruction, Storyboard),
                plan=plan,
                research=research,
            )
        except LLMClientError as exc:
            self.logger.error(
                "event=prompt_failed agent=PromptAgent topic=%r error=%s",
                plan.topic,
                exc,
            )
            raise PromptAgentError(
                f"Failed to build image prompts for topic {plan.topic!r}: {exc}",
                topic=plan.topic,
            ) from exc
        except Exception as exc:
            self.logger.exception(
                "event=prompt_unexpected_error agent=PromptAgent topic=%r",
                plan.topic,
            )
            raise PromptAgentError(
                f"Unexpected failure building prompts for topic {plan.topic!r}: {exc}",
                topic=plan.topic,
            ) from exc

        if not isinstance(storyboard, Storyboard):
            raise PromptAgentError(
                "LLM client returned a non-Storyboard value "
                f"({type(storyboard).__name__})",
                topic=plan.topic,
            )

        validated = _validate_storyboard(storyboard, plan)
        self.logger.info(
            "event=prompt_complete agent=PromptAgent topic=%r scenes=%s",
            validated.topic,
            len(validated.scenes),
        )
        return validated
