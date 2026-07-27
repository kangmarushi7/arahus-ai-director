"""Director agent: turns research into a validated scene plan."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.agents.base import BaseAgent
from src.domain.models import DomainInfo
from src.models.research import ResearchResult
from src.models.storyboard import DirectorPlan
from src.services.llm import LLMClientError

if TYPE_CHECKING:
    from src.services.llm import LLMClient

SCENE_COUNT = 4
MIN_WORDS_PER_SCENE = 60
MAX_WORDS_PER_SCENE = 120

DIRECTOR_PROMPT_TEMPLATE = """You are an award-winning film director renowned for \
meticulously researched, visually striking cinema across many content domains.

Topic: {topic}
{domain_block}
Verified research (treat as authoritative context — do not invent beyond it):
{research_block}

Create exactly {scene_count} scenes that depict this topic.

Rules:
1. Structure the scene sequence to fit the detected domain's storytelling needs \
(use DomainInfo reasoning and keywords as guidance — do not ignore the domain).
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
9. Ground clothing, architecture, props, lighting, and atmosphere in the research \
and domain context.
10. Each scene description must be between {min_words} and {max_words} words.
11. Number scenes with contiguous ids 1..{scene_count} in presentation order.

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


def _format_domain_block(domain_info: DomainInfo | None) -> str:
    if domain_info is None:
        return ""
    keywords = ", ".join(domain_info.keywords) if domain_info.keywords else "(none)"
    return (
        "\nDetected DomainInfo (adjust scene planning to this domain; do not hardcode "
        "a single genre):\n"
        f"- domain: {domain_info.domain.value}\n"
        f"- confidence: {domain_info.confidence:.3f}\n"
        f"- reasoning: {domain_info.reasoning}\n"
        f"- keywords: {keywords}\n"
        f"- suggested_style: {domain_info.suggested_style or '(none)'}\n"
        f"- suggested_camera: {domain_info.suggested_camera or '(none)'}\n"
    )


def generate_director_prompt(
    topic: str,
    research: ResearchResult,
    domain_info: DomainInfo | None = None,
    character_bible: str = "",
) -> str:
    """Build the director prompt for a topic.

    Args:
        topic: Subject or event.
        research: Verified research used as authoritative scene context.
        domain_info: Optional domain classification guiding scene structure.
        character_bible: Optional character-consistency block appended when set.

    Returns:
        The prompt string to send to an LLM.

    Raises:
        ValueError: If ``topic`` is empty or ``research`` is not a ResearchResult.
    """
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("topic must be a non-empty string")
    if not isinstance(research, ResearchResult):
        raise ValueError("research must be a ResearchResult instance")
    if domain_info is not None and not isinstance(domain_info, DomainInfo):
        raise ValueError("domain_info must be a DomainInfo instance when provided")

    prompt = DIRECTOR_PROMPT_TEMPLATE.format(
        topic=" ".join(topic.split()),
        domain_block=_format_domain_block(domain_info),
        research_block=_format_research_block(research),
        scene_count=SCENE_COUNT,
        min_words=MIN_WORDS_PER_SCENE,
        max_words=MAX_WORDS_PER_SCENE,
    )
    bible = character_bible.strip()
    if bible:
        prompt = f"{prompt}\n\n{bible}\n"
    return prompt


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
                f"Scene ids must be contiguous 1..{SCENE_COUNT}; "
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

    def run(
        self,
        topic: str,
        research: ResearchResult,
        domain_info: DomainInfo | None = None,
        character_bible: str = "",
    ) -> DirectorPlan:
        """Plan exactly four scenes for ``topic``.

        Workflow:
            1. Build a director prompt embedding ``research`` and optional domain.
            2. Call ``llm_client.generate_json(..., DirectorPlan)``.
            3. Validate the result (four scenes, titles, no duplicates).
            4. Return the :class:`DirectorPlan` model.

        Args:
            topic: Subject or event.
            research: Verified research used as authoritative context.
            domain_info: Optional domain classification for planning guidance.
            character_bible: Optional character-consistency block for the prompt.

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
        if domain_info is not None and not isinstance(domain_info, DomainInfo):
            raise ValueError("domain_info must be a DomainInfo instance when provided")

        cleaned_topic = " ".join(topic.split())
        self.logger.info(
            "event=director_start agent=DirectorAgent topic=%r "
            "research_topic=%r domain=%s",
            cleaned_topic,
            research.topic,
            domain_info.domain.value if domain_info else None,
        )

        self._log_progress(f"Building director prompt for {cleaned_topic!r}")
        prompt = generate_director_prompt(
            cleaned_topic,
            research,
            domain_info,
            character_bible=character_bible,
        )
        self._log_progress(f"Director prompt ready ({len(prompt)} chars)")
        if self.debug:
            self.logger.debug(
                "event=director_prompt_built agent=DirectorAgent "
                "topic=%r prompt_chars=%s",
                cleaned_topic,
                len(prompt),
            )

        try:
            self._log_progress("Calling director LLM…")
            plan = self._execute(
                lambda: self._llm_client.generate_json(prompt, DirectorPlan),
                topic=cleaned_topic,
                research=research,
                domain_info=domain_info,
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
