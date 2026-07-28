"""Serialize pipeline artifacts for the web lab JSON API."""

from __future__ import annotations

from typing import Any

from src.models.pipeline import PipelineResult


def config_status_payload() -> dict[str, Any]:
    """Return integration readiness flags without secret values."""
    from src.config import get_settings, reload_settings

    reload_settings()
    settings = get_settings()
    has_llm = bool(settings.llm.api_key.get_secret_value().strip())
    try:
        settings.image.require_credentials()
        has_runpod = True
    except RuntimeError:
        has_runpod = False
    try:
        settings.storage.require_complete()
        has_r2 = True
    except RuntimeError:
        has_r2 = False
    has_db = bool(settings.database.url.get_secret_value().strip())
    return {
        "llm": has_llm,
        "runpod": has_runpod,
        "r2": has_r2,
        "database": has_db,
        "allow_stubs": settings.pipeline.allow_stub_services,
        "ready": has_llm and (has_runpod and has_r2 or settings.pipeline.allow_stub_services),
    }


def serialize_result(result: PipelineResult) -> dict[str, Any]:
    """Flatten a :class:`PipelineResult` for the browser."""
    domain = None
    if result.domain_info is not None:
        domain = {
            "domain": result.domain_info.domain.value,
            "confidence": result.domain_info.confidence,
            "reasoning": result.domain_info.reasoning,
        }
    review = result.review
    return {
        "topic": result.topic,
        "run_id": result.run_id,
        "using_stub_services": result.using_stub_services,
        "character_bible": result.character_bible,
        "domain": domain,
        "research": {
            "topic": result.research.topic,
            "time_period": result.research.time_period,
            "location": result.research.location,
            "key_people": result.research.key_people,
            "key_locations": result.research.key_locations,
            "important_events": result.research.important_events,
            "historical_notes": result.research.historical_notes,
            "architecture": result.research.architecture,
            "clothing": result.research.clothing,
            "weapons": result.research.weapons,
        },
        "plan": {
            "topic": result.plan.topic,
            "scenes": [
                {
                    "id": scene.id,
                    "title": scene.title,
                    "description": scene.description,
                }
                for scene in result.plan.scenes
            ],
        },
        "storyboard": {
            "topic": result.storyboard.topic,
            "scenes": [
                {
                    "id": scene.id,
                    "title": scene.title,
                    "description": scene.description,
                    "image_prompt": scene.image_prompt,
                }
                for scene in result.storyboard.scenes
            ],
        },
        "review": {
            "overall_score": review.overall_score,
            "domain_accuracy": review.domain_accuracy,
            "visual_quality": review.visual_quality,
            "scene_continuity": review.scene_continuity,
            "prompt_quality": review.prompt_quality,
            "approved": review.approved,
            "issues": review.issues,
            "recommendations": review.recommendations,
        },
        "images": [
            {
                "scene_id": item.scene_id,
                "title": item.title,
                "prompt": item.prompt,
                "url": item.url,
                "status": item.status,
            }
            for item in result.images
        ],
        "metrics": result.metrics,
    }
