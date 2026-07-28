"""Director agent: cinematic planning via StoryPlanner (Director AI v2).

Public :meth:`DirectorAgent.run` still returns :class:`DirectorPlan` for
pipeline backward compatibility. Internally it uses :class:`StoryPlanner`
to produce structured :class:`~src.models.scene_plan.ScenePlan` rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.agents.base import BaseAgent
from src.director.planner import (
    SCENE_COUNT,
    StoryPlanner,
    StoryPlannerError,
    generate_story_planner_prompt,
    validate_story_plan,
)
from src.domain.models import DomainInfo
from src.models.research import ResearchResult
from src.models.scene_plan import StoryPlan
from src.models.storyboard import DirectorPlan
from src.services.llm import LLMClientError

if TYPE_CHECKING:
    from src.services.llm import LLMClient

# Re-export legacy names used by tests / callers.
MIN_WORDS_PER_SCENE = 60
MAX_WORDS_PER_SCENE = 120

# Backward-compatible alias: older tests import generate_director_prompt.
generate_director_prompt = generate_story_planner_prompt


class DirectorAgentError(Exception):
    """Raised when the director agent cannot produce a :class:`DirectorPlan`."""

    def __init__(self, message: str, *, topic: str | None = None) -> None:
        super().__init__(message)
        self.topic = topic


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

    if plan.scene_plans:
        try:
            validate_story_plan(
                StoryPlan(topic=plan.topic, scenes=list(plan.scene_plans)),
                topic=topic,
            )
        except StoryPlannerError as exc:
            raise DirectorAgentError(str(exc), topic=topic) from exc

    return plan


class DirectorAgent(BaseAgent[DirectorPlan]):
    """Produces a validated :class:`DirectorPlan` with cinematic ScenePlans.

    Depends on an injected :class:`~src.services.llm.LLMClient`. Planning is
    delegated to :class:`~src.director.planner.StoryPlanner`.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        story_planner: StoryPlanner | None = None,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
        debug: bool | None = None,
    ) -> None:
        """Store the injected LLM client and optional StoryPlanner."""
        super().__init__(
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            debug=debug,
        )
        self._llm_client = llm_client
        self._planner = story_planner or StoryPlanner(llm_client)

    @property
    def planner(self) -> StoryPlanner:
        """Underlying cinematic :class:`StoryPlanner`."""
        return self._planner

    def run(
        self,
        topic: str,
        research: ResearchResult,
        domain_info: DomainInfo | None = None,
        character_bible: str = "",
    ) -> DirectorPlan:
        """Plan exactly four cinematic scenes for ``topic``.

        Workflow:
            1. :class:`StoryPlanner` produces a :class:`StoryPlan` of ScenePlans.
            2. Convert to :class:`DirectorPlan` (BC ``scenes`` + ``scene_plans``).
            3. Validate and return.

        Args:
            topic: Subject or event.
            research: Verified research used as authoritative context.
            domain_info: Optional domain classification for planning guidance.
            character_bible: Optional character-consistency block for the prompt.

        Returns:
            The validated director plan (with ``scene_plans`` when available).

        Raises:
            ValueError: If ``topic`` or ``research`` is invalid.
            DirectorAgentError: If planning or validation fails.
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
            "research_topic=%r domain=%s mode=story_planner_v2",
            cleaned_topic,
            research.topic,
            domain_info.domain.value if domain_info else None,
        )

        self._log_progress(f"Building cinematic story plan for {cleaned_topic!r}")
        try:
            self._log_progress("Calling StoryPlanner…")
            story_plan = self._execute(
                lambda: self._planner.plan(
                    cleaned_topic,
                    research,
                    domain_info,
                    character_bible=character_bible,
                ),
                topic=cleaned_topic,
                research=research,
                domain_info=domain_info,
            )
        except StoryPlannerError as exc:
            self.logger.error(
                "event=director_failed agent=DirectorAgent topic=%r error=%s",
                cleaned_topic,
                exc,
            )
            raise DirectorAgentError(
                f"Failed to direct topic {cleaned_topic!r}: {exc}",
                topic=cleaned_topic,
            ) from exc
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

        if not isinstance(story_plan, StoryPlan):
            raise DirectorAgentError(
                "StoryPlanner returned a non-StoryPlan value "
                f"({type(story_plan).__name__})",
                topic=cleaned_topic,
            )

        plan = story_plan.to_director_plan()
        validated = _validate_plan(plan, topic=cleaned_topic)
        self.logger.info(
            "event=director_complete agent=DirectorAgent topic=%r scenes=%s "
            "scene_plans=%s",
            validated.topic,
            len(validated.scenes),
            len(validated.scene_plans or []),
        )
        return validated
