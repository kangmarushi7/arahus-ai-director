"""Director agent: turns research into a chronological, validated scene plan."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.agents.base import BaseAgent
from src.models.research import ResearchResult
from src.models.storyboard import DirectorPlan
from src.services.llm import LLMClientError

if TYPE_CHECKING:
    from src.services.llm import LLMClient

SCENE_COUNT = 4
MIN_WORDS_PER_SCENE = 60
MAX_WORDS_PER_SCENE = 120

DIRECTOR_PROMPT_TEMPLATE = """You are an award-winning historical film director \
renowned for meticulously researched, visually striking period cinema.

Topic: {topic}

Verified research (treat as authoritative context — do not invent beyond it):
{research_block}

Create exactly {scene_count} scenes that depict this topic.

Rules:
1. Present the scenes in strict chronological order from earliest to latest.
2. Generate exactly {scene_count} scenes — no more, no fewer.
3. Do not hallucinate people, places, objects, or events that conflict with the \
verified research. Prefer omission over invention.
4. Do not create duplicate or near-duplicate scenes. Each scene must advance \
the story to a distinct moment.
5. Each scene must include a concise "title" and a visual "description".
6. Focus entirely on visual storytelling. Describe only what should appear in \
the image.
7. Do not write narration, dialogue, voice-over, on-screen titles, or backstory.
8. Do not include camera instructions unless a specific shot choice is essential \
to the meaning of the scene.
9. In every scene, include period-accurate clothing, architecture, weapons, \
lighting, and atmosphere grounded in the research.
10. Each scene description must be between {min_words} and {max_words} words.

Return ONLY valid JSON.

Use exactly this schema:

{{
  "topic": "{topic}",
  "scenes": [
    {{
      "id": 1,
      "title": "...",
      "description": "..."
    }},
    {{
      "id": 2,
      "title": "...",
      "description": "..."
    }},
    {{
      "id": 3,
      "title": "...",
      "description": "..."
    }},
    {{
      "id": 4,
      "title": "...",
      "description": "..."
    }}
  ]
}}

Return no markdown.

Return no explanation.

Return only JSON."""


class DirectorAgentError(Exception):
    """Raised when the director agent cannot produce a :class:`DirectorPlan`."""

    def __init__(self, message: str, *, topic: str | None = None) -> None:
        super().__init__(message)
        self.topic = topic


def _format_research_block(research: ResearchResult) -> str:
    """Render verified research as context for the director prompt."""
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


def generate_director_prompt(topic: str, research: ResearchResult) -> str:
    """Build the director prompt for a historical topic.

    Args:
        topic: Historical subject or event, e.g. "Fall of Constantinople 1453".
        research: Verified research used as authoritative scene context.

    Returns:
        The prompt string to send to an LLM.

    Raises:
        ValueError: If ``topic`` is empty or ``research`` is not a ResearchResult.
    """
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("topic must be a non-empty string")
    if not isinstance(research, ResearchResult):
        raise ValueError("research must be a ResearchResult instance")

    return DIRECTOR_PROMPT_TEMPLATE.format(
        topic=" ".join(topic.split()),
        research_block=_format_research_block(research),
        scene_count=SCENE_COUNT,
        min_words=MIN_WORDS_PER_SCENE,
        max_words=MAX_WORDS_PER_SCENE,
    )


def _validate_plan(plan: DirectorPlan, *, topic: str) -> DirectorPlan:
    """Enforce director invariants beyond basic Pydantic shape checks."""
    if len(plan.scenes) != SCENE_COUNT:
        raise DirectorAgentError(
            f"DirectorPlan must contain exactly {SCENE_COUNT} scenes, "
            f"got {len(plan.scenes)}",
            topic=topic,
        )

    titles: list[str] = []
    for index, scene in enumerate(plan.scenes, start=1):
        if scene.id != index:
            raise DirectorAgentError(
                f"Scene ids must be chronological 1..{SCENE_COUNT}; "
                f"expected id={index}, got id={scene.id}",
                topic=topic,
            )
        if not scene.title.strip():
            raise DirectorAgentError(
                f"Scene {index} is missing a title",
                topic=topic,
            )
        if not scene.description.strip():
            raise DirectorAgentError(
                f"Scene {index} is missing a description",
                topic=topic,
            )

        normalized_title = " ".join(scene.title.lower().split())
        if normalized_title in titles:
            raise DirectorAgentError(
                f"Duplicate scene title detected: {scene.title!r}",
                topic=topic,
            )
        titles.append(normalized_title)

    return plan


class DirectorAgent(BaseAgent[DirectorPlan]):
    """Produces a validated :class:`DirectorPlan` from a topic and research.

    Depends only on an injected :class:`~src.services.llm.LLMClient`. Provider
    details stay outside this class.
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

    def run(self, topic: str, research: ResearchResult) -> DirectorPlan:
        """Plan exactly four chronological scenes for ``topic``.

        Workflow:
            1. Build a director prompt that embeds ``research`` as context.
            2. Call ``llm_client.generate_json(..., DirectorPlan)``.
            3. Validate the result (four scenes, titles, no duplicates).
            4. Return the :class:`DirectorPlan` model.

        Args:
            topic: Historical subject or event.
            research: Verified research used as authoritative context.

        Returns:
            The validated director plan.

        Raises:
            ValueError: If ``topic`` or ``research`` is invalid.
            DirectorAgentError: If the LLM call or plan validation fails.
        """
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("topic must be a non-empty string")
        if not isinstance(research, ResearchResult):
            raise ValueError("research must be a ResearchResult instance")

        cleaned_topic = " ".join(topic.split())
        self.logger.info(
            "event=director_start agent=DirectorAgent topic=%r "
            "research_topic=%r",
            cleaned_topic,
            research.topic,
        )

        prompt = generate_director_prompt(cleaned_topic, research)
        if self.debug:
            self.logger.debug(
                "event=director_prompt_built agent=DirectorAgent "
                "topic=%r prompt_chars=%s",
                cleaned_topic,
                len(prompt),
            )

        try:
            plan = self._execute(
                lambda: self._llm_client.generate_json(prompt, DirectorPlan),
                topic=cleaned_topic,
                research=research,
            )
        except LLMClientError as exc:
            self.logger.error(
                "event=director_failed agent=DirectorAgent topic=%r error=%s",
                cleaned_topic,
                exc,
            )
            raise DirectorAgentError(
                f"Failed to direct topic {cleaned_topic!r}: {exc}",
                topic=cleaned_topic,
            ) from exc
        except Exception as exc:
            self.logger.exception(
                "event=director_unexpected_error agent=DirectorAgent topic=%r",
                cleaned_topic,
            )
            raise DirectorAgentError(
                f"Unexpected failure directing topic {cleaned_topic!r}: {exc}",
                topic=cleaned_topic,
            ) from exc

        if not isinstance(plan, DirectorPlan):
            raise DirectorAgentError(
                "LLM client returned a non-DirectorPlan value "
                f"({type(plan).__name__})",
                topic=cleaned_topic,
            )

        validated = _validate_plan(plan, topic=cleaned_topic)
        self.logger.info(
            "event=director_complete agent=DirectorAgent topic=%r scenes=%s",
            validated.topic,
            len(validated.scenes),
        )
        return validated
