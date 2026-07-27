"""Milestones 2–5 – exercise Research, Director, Prompt, and Review agents."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Windows consoles often default to a legacy code page; force UTF-8 output.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from src.agents.director import DirectorAgent
from src.agents.prompt import PromptAgent
from src.agents.research import ResearchAgent
from src.agents.review import ReviewAgent
from src.config import get_settings, reload_settings
from src.models.research import ResearchResult
from src.models.review import ReviewResult
from src.models.storyboard import DirectorPlan, Scene, Storyboard
from src.services.llm_factory import create_llm


TOPIC = "Fall of Constantinople"
ARTIFACT_DIR = Path("artifacts")


def _print_heading(title: str) -> None:
    print(f"\n=== {title} ===")


def milestone_research() -> ResearchResult:
    """Milestone 2 – ResearchAgent returns a validated ResearchResult."""
    _print_heading("Milestone 2 – Research Agent")
    settings = get_settings()
    agent = ResearchAgent(create_llm(settings.llm.research_model), max_retries=2)
    result = agent.run(TOPIC)

    assert isinstance(result, ResearchResult)
    assert "Constantinople" in result.topic or "Constantinople" in result.location
    ARTIFACT_DIR.mkdir(exist_ok=True)
    (ARTIFACT_DIR / "research.json").write_text(
        result.model_dump_json(indent=2),
        encoding="utf-8",
    )
    print(result.model_dump_json(indent=2))
    print("Research Agent: PASS")
    return result


def milestone_director(research: ResearchResult) -> DirectorPlan:
    """Milestone 3 – DirectorAgent returns four chronological scenes."""
    _print_heading("Milestone 3 – Director Agent")
    settings = get_settings()
    agent = DirectorAgent(create_llm(settings.llm.director_model), max_retries=2)
    plan = agent.run(TOPIC, research)

    assert isinstance(plan, DirectorPlan)
    assert len(plan.scenes) == 4
    assert plan.scenes[0].title
    assert plan.scenes[3].description
    for scene in plan.scenes:
        print(f"Scene {scene.id}: {scene.title}")
        print(scene.description)
        print()
    print("Director Agent: PASS")
    return plan


def milestone_prompt(plan: DirectorPlan, research: ResearchResult) -> Storyboard:
    """Milestone 4 – PromptAgent returns FLUX-ready image prompts."""
    _print_heading("Milestone 4 – Prompt Agent")
    settings = get_settings()
    agent = PromptAgent(create_llm(settings.llm.prompt_model), max_retries=2)
    storyboard = agent.run(plan, research)

    assert isinstance(storyboard, Storyboard)
    assert len(storyboard.scenes) == 4
    for scene in storyboard.scenes:
        assert scene.image_prompt
        print(f"--- Scene {scene.id}: {scene.title} ---")
        print(scene.image_prompt)
        print()
    print("Prompt Agent: PASS (inspect prompts above)")
    return storyboard


def milestone_review(good_storyboard: Storyboard) -> None:
    """Milestone 5 – ReviewAgent rejects bad boards and approves good ones."""
    _print_heading("Milestone 5 – Review Agent")
    settings = get_settings()
    agent = ReviewAgent(create_llm(settings.llm.review_model), max_retries=2)

    bad = Storyboard(
        topic=TOPIC,
        scenes=[
            Scene(
                id=1,
                title="Laser Assault",
                description="Ottoman soldiers fire laser guns at the walls.",
                image_prompt=(
                    "Fall of Constantinople with laser guns, modern tanks, "
                    "and an iPhone on the battlefield, neon cyberpunk lighting"
                ),
            ),
            Scene(
                id=2,
                title="Tank Charge",
                description="Modern tanks roll through the Byzantine streets.",
                image_prompt="modern tanks in Constantinople, anachronistic warfare",
            ),
            Scene(
                id=3,
                title="Selfie Break",
                description="A janissary takes a selfie with an iPhone.",
                image_prompt="janissary holding iPhone selfie stick",
            ),
            Scene(
                id=4,
                title="Helicopter Evacuation",
                description="Helicopters evacuate the emperor.",
                image_prompt="attack helicopters over Hagia Sophia",
            ),
        ],
    )

    bad_review = agent.run(bad)
    assert isinstance(bad_review, ReviewResult)
    print("Bad storyboard review:")
    print(json.dumps(bad_review.model_dump(), indent=2))
    assert bad_review.approved is False
    assert bad_review.overall_score < 85

    good_review = agent.run(good_storyboard)
    assert isinstance(good_review, ReviewResult)
    print("Good storyboard review:")
    print(json.dumps(good_review.model_dump(), indent=2))
    assert good_review.approved is True
    assert good_review.overall_score >= 85
    print("Review Agent: PASS")


def main() -> int:
    """Run milestones 2–5 sequentially against live OpenRouter models."""
    reload_settings()
    get_settings().llm.require_api_key()

    research = milestone_research()
    plan = milestone_director(research)
    storyboard = milestone_prompt(plan, research)
    milestone_review(storyboard)
    print("\nAll agent milestones passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - top-level test runner
        print(f"FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
