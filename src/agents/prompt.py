"""Prompt agent: decides scene content; PromptComposer builds final prompts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import Field

from src.agents.base import BaseAgent
from src.domain.config_loader import ConfigLoader
from src.domain.models import DomainInfo, DomainType
from src.domain.prompt_context import DomainPromptContext
from src.models.base import StrictModel
from src.models.research import ResearchResult
from src.models.storyboard import DirectorPlan, Scene, Storyboard
from src.prompt.composer import PromptComposer
from src.monitoring.metrics import STAGE_PROMPT_COMPOSER
from src.monitoring.profiler import measure_stage
from src.services.llm import LLMClientError

if TYPE_CHECKING:
    from src.services.llm import LLMClient


class SceneContentBrief(StrictModel):
    """LLM-decided visual content for one scene (not the final image prompt)."""

    id: int = Field(ge=1)
    title: str
    description: str
    subject: str
    environment: str = ""
    action: str = ""


class SceneContentPlan(StrictModel):
    """LLM output: per-scene subject / environment / action briefs."""

    topic: str
    scenes: list[SceneContentBrief] = Field(min_length=1)


PROMPT_CONTENT_TEMPLATE = """You are a visual content designer for a multi-domain \
film / image production system.

Your only job is to decide what appears in each scene. Do NOT write final FLUX \
prompts. Do NOT append style, camera, lighting, quality tags, or negative prompts \
— those are applied later by a separate composition engine.

Topic: {topic}
{domain_block}
Director scenes (preserve id, title, and description exactly):
{scenes_block}

Verified research (use as authoritative visual reference):
{research_block}

For every scene, fill:
- subject: primary figure(s) / focal object
- environment: setting, architecture, atmosphere
- action: what is happening in the frame (may be empty if static)

Rules:
1. Keep every scene's "id", "title", and "description" exactly as given.
2. Produce exactly one content brief per scene, in the same order.
3. Describe only concrete visual content — no style packs, camera presets, or \
quality tag lists.
4. Do not write narration, dialogue, or backstory.
5. Ground clothing, architecture, props, and materials in the verified research.
6. Adapt terminology to the detected domain when provided.
7. Return no markdown.
8. Return no explanation.
9. Return ONLY valid JSON.

Use exactly this schema:

{{
  "topic": "{topic}",
  "scenes": [
    {{
      "id": 1,
      "title": "...",
      "description": "...",
      "subject": "...",
      "environment": "...",
      "action": "..."
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
    """Render verified research as visual reference."""
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


def _format_domain_block(
    domain_info: DomainInfo | None,
    prompt_context: DomainPromptContext | None,
) -> str:
    lines: list[str] = []
    if domain_info is not None:
        lines.extend(
            [
                "Detected DomainInfo:",
                f"- domain: {domain_info.domain.value}",
                f"- confidence: {domain_info.confidence:.3f}",
                f"- reasoning: {domain_info.reasoning}",
            ]
        )
    if prompt_context is not None:
        lines.extend(
            [
                "Domain prompt context is applied later by PromptComposer "
                "(do not copy these into subject/environment/action):",
                f"- style preset present: {bool(prompt_context.style)}",
                f"- camera preset present: {bool(prompt_context.camera)}",
                f"- lighting preset present: {bool(prompt_context.lighting)}",
            ]
        )
    if not lines:
        return ""
    return "\n" + "\n".join(lines) + "\n"


def generate_prompt_agent_prompt(
    plan: DirectorPlan,
    research: ResearchResult,
    domain_info: DomainInfo | None = None,
    prompt_context: DomainPromptContext | None = None,
    character_bible: str = "",
) -> str:
    """Build the LLM instruction that decides per-scene visual content.

    Args:
        plan: The director's validated scene plan.
        research: Verified research for visual grounding.
        domain_info: Optional domain classification.
        prompt_context: Optional YAML domain prompt context (not inlined into
            final prompts here — composer applies it).
        character_bible: Optional character-consistency block appended when set.

    Returns:
        The prompt string to send to an LLM.

    Raises:
        ValueError: If ``plan`` or ``research`` has the wrong type.
    """
    if not isinstance(plan, DirectorPlan):
        raise ValueError("plan must be a DirectorPlan instance")
    if not isinstance(research, ResearchResult):
        raise ValueError("research must be a ResearchResult instance")

    prompt = PROMPT_CONTENT_TEMPLATE.format(
        topic=plan.topic,
        domain_block=_format_domain_block(domain_info, prompt_context),
        scenes_block=_format_scenes_block(plan),
        research_block=_format_research_block(research),
    )
    bible = character_bible.strip()
    if bible:
        prompt = f"{prompt}\n\n{bible}\n"
    return prompt


def _validate_content_plan(
    content: SceneContentPlan,
    plan: DirectorPlan,
) -> SceneContentPlan:
    """Enforce content-plan invariants against the director plan."""
    if len(content.scenes) != len(plan.scenes):
        raise PromptAgentError(
            "Content plan scene count must match the director plan: "
            f"expected {len(plan.scenes)}, got {len(content.scenes)}",
            topic=plan.topic,
        )

    for expected, scene in zip(plan.scenes, content.scenes, strict=True):
        if scene.id != expected.id:
            raise PromptAgentError(
                f"Content scene id mismatch: expected {expected.id}, "
                f"got {scene.id}",
                topic=plan.topic,
            )
        if not scene.subject.strip():
            raise PromptAgentError(
                f"Scene {scene.id} is missing a subject",
                topic=plan.topic,
            )

    return content


def _resolve_prompt_context(
    *,
    prompt_context: DomainPromptContext | None,
    domain_info: DomainInfo | None,
    config_loader: ConfigLoader,
) -> DomainPromptContext:
    if prompt_context is not None:
        return prompt_context
    domain = domain_info.domain if domain_info is not None else DomainType.GENERAL
    return config_loader.load(domain)


class PromptAgent(BaseAgent[Storyboard]):
    """Produces a :class:`Storyboard` of composed FLUX image prompts.

    The LLM decides scene content only. :class:`PromptComposer` merges domain
    defaults (style, camera, lighting, composition, quality tags, negatives)
    into the final ``image_prompt`` strings. This agent never calls RunPod.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        prompt_composer: PromptComposer | None = None,
        config_loader: ConfigLoader | None = None,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
        debug: bool | None = None,
    ) -> None:
        """Store injected collaborators.

        Args:
            llm_client: Client used to request validated JSON content briefs.
            prompt_composer: Deterministic composer for final prompts.
            config_loader: YAML domain config loader used when prompt_context
                is omitted (fallback to GENERAL / domain_info.domain).
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
        self._composer = prompt_composer or PromptComposer()
        self._config_loader = config_loader or ConfigLoader()

    def run(
        self,
        plan: DirectorPlan,
        research: ResearchResult,
        domain_info: DomainInfo | None = None,
        prompt_context: DomainPromptContext | None = None,
        character_bible: str = "",
    ) -> Storyboard:
        """Decide scene content, then compose final image prompts.

        Workflow:
            1. Ask the LLM for subject / environment / action per scene.
            2. Validate briefs against the director plan.
            3. :meth:`PromptComposer.compose_from_domain` for each scene.
            4. Return a :class:`Storyboard` with composed ``image_prompt`` values.

        Args:
            plan: The director's validated scene plan.
            research: Verified research used as visual context.
            domain_info: Optional domain classification.
            prompt_context: Optional YAML domain prompt defaults.
            character_bible: Optional character-consistency block for the prompt.

        Returns:
            The validated storyboard containing composed image prompts only.

        Raises:
            ValueError: If ``plan`` or ``research`` is invalid.
            PromptAgentError: If the LLM call, validation, or compose fails.
        """
        if not isinstance(plan, DirectorPlan):
            raise ValueError("plan must be a DirectorPlan instance")
        if not isinstance(research, ResearchResult):
            raise ValueError("research must be a ResearchResult instance")
        if domain_info is not None and not isinstance(domain_info, DomainInfo):
            raise ValueError("domain_info must be a DomainInfo instance when provided")
        if prompt_context is not None and not isinstance(
            prompt_context, DomainPromptContext
        ):
            raise ValueError(
                "prompt_context must be a DomainPromptContext when provided"
            )

        resolved_context = _resolve_prompt_context(
            prompt_context=prompt_context,
            domain_info=domain_info,
            config_loader=self._config_loader,
        )

        self.logger.info(
            "event=prompt_start agent=PromptAgent topic=%r scenes=%s domain=%s "
            "style_preset=%r camera_preset=%r",
            plan.topic,
            len(plan.scenes),
            resolved_context.domain.value,
            resolved_context.style[:80],
            resolved_context.camera[:80],
        )

        self._log_progress(f"Building scene-content instruction for {plan.topic!r}")
        instruction = generate_prompt_agent_prompt(
            plan,
            research,
            domain_info=domain_info,
            prompt_context=resolved_context,
            character_bible=character_bible,
        )
        self._log_progress(f"Content instruction ready ({len(instruction)} chars)")

        try:
            self._log_progress("Calling prompt LLM for scene content…")
            content = self._execute(
                lambda: self._llm_client.generate_json(instruction, SceneContentPlan),
                plan=plan,
                research=research,
                domain_info=domain_info,
            )
        except LLMClientError as exc:
            self.logger.error(
                "event=prompt_failed agent=PromptAgent topic=%r error=%s",
                plan.topic,
                exc,
            )
            raise PromptAgentError(
                f"Failed to build scene content for topic {plan.topic!r}: {exc}",
                topic=plan.topic,
            ) from exc
        except Exception as exc:
            self.logger.exception(
                "event=prompt_unexpected_error agent=PromptAgent topic=%r",
                plan.topic,
            )
            raise PromptAgentError(
                f"Unexpected failure building scene content for topic "
                f"{plan.topic!r}: {exc}",
                topic=plan.topic,
            ) from exc

        if not isinstance(content, SceneContentPlan):
            raise PromptAgentError(
                "LLM client returned a non-SceneContentPlan value "
                f"({type(content).__name__})",
                topic=plan.topic,
            )

        validated = _validate_content_plan(content, plan)
        with measure_stage(STAGE_PROMPT_COMPOSER):
            storyboard = self._compose_storyboard(validated, resolved_context)
        self.logger.info(
            "event=prompt_complete agent=PromptAgent topic=%r scenes=%s "
            "domain=%s",
            storyboard.topic,
            len(storyboard.scenes),
            resolved_context.domain.value,
        )
        return storyboard

    def _compose_storyboard(
        self,
        content: SceneContentPlan,
        prompt_context: DomainPromptContext,
    ) -> Storyboard:
        """Merge domain defaults into each scene via :class:`PromptComposer`."""
        scenes: list[Scene] = []
        for brief in content.scenes:
            self._log_progress(
                f"Composing final prompt for scene {brief.id}: {brief.title!r}"
            )
            final = self._composer.compose_from_domain(
                prompt_context,
                subject=brief.subject,
                environment=brief.environment,
                action=brief.action,
                extra_details=brief.description,
                metadata={
                    "scene_id": brief.id,
                    "scene_title": brief.title,
                },
            )
            scenes.append(
                Scene(
                    id=brief.id,
                    title=brief.title,
                    description=brief.description,
                    image_prompt=final.positive_prompt,
                    image=None,
                )
            )
            self.logger.info(
                "event=prompt_composed scene_id=%s domain=%s "
                "positive_chars=%s negative_chars=%s style_pack=%r camera=%r",
                brief.id,
                prompt_context.domain.value,
                len(final.positive_prompt),
                len(final.negative_prompt),
                prompt_context.style[:60],
                prompt_context.camera[:60],
            )

        return Storyboard(topic=content.topic, scenes=scenes)
