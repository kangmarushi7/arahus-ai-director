"""Unit tests for domain-aware review prompts and ReviewResult aliases."""

from __future__ import annotations

from src.agents.review import domain_review_rubric, generate_review_prompt
from src.domain.models import DomainInfo, DomainType
from src.models.review import ReviewResult
from src.models.storyboard import Scene, Storyboard


def _storyboard() -> Storyboard:
    scenes = [
        Scene(
            id=i,
            title=f"Scene {i}",
            description=f"Description {i}",
            image_prompt=f"a detailed prompt {i}",
        )
        for i in range(1, 5)
    ]
    return Storyboard(topic="Test topic", scenes=scenes)


def test_review_result_accepts_historical_accuracy_alias() -> None:
    result = ReviewResult(
        overall_score=90,
        historical_accuracy=88,
        visual_quality=90,
        scene_continuity=91,
        prompt_quality=89,
        approved=True,
    )
    assert result.domain_accuracy == 88
    assert result.historical_accuracy == 88


def test_review_prompt_is_domain_aware() -> None:
    info = DomainInfo(
        domain=DomainType.FANTASY,
        confidence=0.9,
        reasoning="dragons",
    )
    prompt = generate_review_prompt(_storyboard(), domain_info=info)
    assert "fantasy" in prompt.lower()
    assert "domain_accuracy" in prompt
    assert "historical film QA" not in prompt
    assert "mythic" in domain_review_rubric(DomainType.FANTASY).lower()
