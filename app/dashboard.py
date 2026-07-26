"""AI Director Studio – Streamlit dashboard wired to DirectorPipeline."""

from __future__ import annotations

import traceback
from typing import Any

import streamlit as st

from src.api import generate_pipeline_result
from src.config import reload_settings
from src.models.pipeline import PipelineResult
from src.pipeline import PipelineValidationError

# ---------------------------------------------------------------------------
# Placeholder payloads – shown before the first successful Generate.
# ---------------------------------------------------------------------------

PLACEHOLDER_TOPIC = "Fall of Constantinople"

PLACEHOLDER_RESEARCH: dict[str, Any] = {
    "topic": PLACEHOLDER_TOPIC,
    "time_period": "1453 CE",
    "location": "Constantinople (modern Istanbul)",
    "key_people": ["Mehmed II", "Constantine XI Palaiologos"],
    "architecture": ["Theodosian Walls", "Hagia Sophia"],
    "weapons": ["Basilisk cannon", "Greek fire", "crossbow"],
    "clothing": ["Janissary uniform", "Byzantine imperial regalia"],
}

PLACEHOLDER_DIRECTOR: dict[str, Any] = {
    "topic": PLACEHOLDER_TOPIC,
    "scenes": [
        {
            "id": 1,
            "title": "Ottoman Fleet Enters the Golden Horn",
            "description": "Dawn light over Ottoman galleys approaching the walls.",
        },
        {
            "id": 2,
            "title": "Basilisk Cannon Bombards the Walls",
            "description": "Late-afternoon artillery fire against the Theodosian Walls.",
        },
        {
            "id": 3,
            "title": "Breach of the Theodosian Walls",
            "description": "Janissaries surge through a rubble-strewn breach.",
        },
        {
            "id": 4,
            "title": "Hagia Sophia and the Aftermath",
            "description": "Smoke and fading light mark the end of the siege.",
        },
    ],
}

PLACEHOLDER_STORYBOARD: dict[str, Any] = {
    "topic": PLACEHOLDER_TOPIC,
    "scenes": [
        {
            "id": scene["id"],
            "title": scene["title"],
            "description": scene["description"],
            "image_prompt": (
                f"{scene['title']}, period-accurate architecture and clothing, "
                "dramatic lighting, ultra detailed, 35mm film look"
            ),
        }
        for scene in PLACEHOLDER_DIRECTOR["scenes"]
    ],
}

PLACEHOLDER_REVIEW: dict[str, Any] = {
    "overall_score": 90.0,
    "historical_accuracy": 88.0,
    "visual_quality": 91.0,
    "scene_continuity": 93.0,
    "prompt_quality": 89.0,
    "issues": ["Minor flag-detail uncertainty for 1453."],
    "recommendations": ["Prefer period-accurate Janissary headgear wording."],
    "approved": True,
}

PLACEHOLDER_METRICS: dict[str, Any] = {
    "pipeline_duration_seconds": 0.0,
    "llm_latency_average_seconds": 0.0,
    "runpod_latency_average_seconds": 0.0,
    "r2_upload_latency_average_seconds": 0.0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "estimated_cost": 0.0,
    "images_generated": 0,
    "retry_count": 0,
}

PLACEHOLDER_IMAGES: list[dict[str, Any]] = [
    {
        "scene_id": str(scene["id"]),
        "title": scene["title"],
        "url": "",
        "status": "Not generated yet",
    }
    for scene in PLACEHOLDER_DIRECTOR["scenes"]
]


# ---------------------------------------------------------------------------
# Session / pipeline helpers
# ---------------------------------------------------------------------------


def _init_session_state() -> None:
    """Ensure studio session keys exist."""
    defaults: dict[str, Any] = {
        "pipeline_result": None,
        "last_error": None,
        "last_topic": PLACEHOLDER_TOPIC,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _result_payloads(
    result: PipelineResult | None,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
]:
    """Map a pipeline result (or placeholders) into section payloads."""
    if result is None:
        return (
            PLACEHOLDER_RESEARCH,
            PLACEHOLDER_DIRECTOR,
            PLACEHOLDER_STORYBOARD,
            PLACEHOLDER_REVIEW,
            PLACEHOLDER_METRICS,
            PLACEHOLDER_IMAGES,
        )

    images = [
        {
            "scene_id": str(image.scene_id),
            "title": image.title,
            "url": image.url or "",
            "status": image.status,
            "prompt": image.prompt,
        }
        for image in result.images
    ]
    return (
        result.research.model_dump(mode="json"),
        result.plan.model_dump(mode="json"),
        result.storyboard.model_dump(mode="json"),
        result.review.model_dump(mode="json"),
        result.metrics,
        images,
    )


def run_pipeline(topic: str) -> None:
    """Execute DirectorPipeline and store intermediates in session state.

    Exceptions are captured into session state so the Streamlit UI never crashes.
    """
    st.session_state["last_error"] = None
    st.session_state["last_topic"] = topic

    try:
        reload_settings()
        with st.spinner(f"Directing “{topic}”… this can take several minutes"):
            result = generate_pipeline_result(topic)
        st.session_state["pipeline_result"] = result
        st.success(f"Pipeline completed for **{topic}**.")
    except PipelineValidationError as exc:
        st.session_state["pipeline_result"] = None
        st.session_state["last_error"] = {
            "type": "PipelineValidationError",
            "message": str(exc),
            "topic": exc.topic,
            "attempts": exc.attempts,
            "review": exc.review.model_dump(mode="json"),
        }
        st.error(f"Storyboard rejected after review retries: {exc}")
    except Exception as exc:  # noqa: BLE001 - keep the UI alive
        st.session_state["pipeline_result"] = None
        st.session_state["last_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        st.error(f"Pipeline failed: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------


def render_header() -> None:
    """Render the studio title and short description."""
    st.title("AI Director Studio")
    st.caption(
        "Internal console for historical research, direction, prompting, "
        "review, and image generation."
    )


def render_topic_controls() -> tuple[str, bool]:
    """Render the topic input and generate button.

    Returns:
        A tuple of ``(topic, generate_clicked)``.
    """
    topic = st.text_input(
        "Historical Topic",
        value=st.session_state.get("last_topic", PLACEHOLDER_TOPIC),
        placeholder="e.g. Fall of Constantinople",
        help="Enter the historical subject the director pipeline should film.",
    )
    generate_clicked = st.button("Generate", type="primary", use_container_width=False)
    return topic.strip(), generate_clicked


def render_error_banner() -> None:
    """Show the last captured pipeline error, if any."""
    error = st.session_state.get("last_error")
    if not error:
        return

    with st.expander("Last error details", expanded=False):
        st.json(error)


def render_research_section(research: dict[str, Any]) -> None:
    """Render the research expandable section."""
    with st.expander("Research", expanded=False):
        st.subheader(research.get("topic", "Untitled topic"))
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"**Time period:** {research.get('time_period', '—')}")
            st.markdown(f"**Location:** {research.get('location', '—')}")
            st.markdown("**Key people**")
            st.write(research.get("key_people") or [])
        with col_b:
            st.markdown("**Architecture**")
            st.write(research.get("architecture") or [])
            st.markdown("**Weapons**")
            st.write(research.get("weapons") or [])
            st.markdown("**Clothing**")
            st.write(research.get("clothing") or [])
        st.json(research)


def render_director_section(plan: dict[str, Any]) -> None:
    """Render the director plan expandable section."""
    with st.expander("Director", expanded=False):
        st.markdown(f"**Topic:** {plan.get('topic', '—')}")
        for scene in plan.get("scenes") or []:
            st.markdown(
                f"### Scene {scene.get('id', '?')}: {scene.get('title', 'Untitled')}"
            )
            st.write(scene.get("description", ""))
            st.divider()


def render_storyboard_section(storyboard: dict[str, Any]) -> None:
    """Render the storyboard / image-prompt expandable section."""
    with st.expander("Storyboard", expanded=False):
        st.markdown(f"**Topic:** {storyboard.get('topic', '—')}")
        for scene in storyboard.get("scenes") or []:
            st.markdown(
                f"### Scene {scene.get('id', '?')}: {scene.get('title', 'Untitled')}"
            )
            st.markdown("**Description**")
            st.write(scene.get("description", ""))
            st.markdown("**Image prompt**")
            st.code(scene.get("image_prompt", ""), language=None)
            st.divider()


def render_review_section(review: dict[str, Any]) -> None:
    """Render the review expandable section."""
    with st.expander("Review", expanded=False):
        approved = bool(review.get("approved"))
        st.markdown(f"**Approved:** {'Yes' if approved else 'No'}")

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Overall", f"{review.get('overall_score', 0):.0f}")
        m2.metric("History", f"{review.get('historical_accuracy', 0):.0f}")
        m3.metric("Visual", f"{review.get('visual_quality', 0):.0f}")
        m4.metric("Continuity", f"{review.get('scene_continuity', 0):.0f}")
        m5.metric("Prompts", f"{review.get('prompt_quality', 0):.0f}")

        st.markdown("**Issues**")
        st.write(review.get("issues") or ["None"])
        st.markdown("**Recommendations**")
        st.write(review.get("recommendations") or ["None"])


def render_metrics_section(metrics: dict[str, Any]) -> None:
    """Render the metrics expandable section."""
    with st.expander("Metrics", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Pipeline (s)", f"{metrics.get('pipeline_duration_seconds', 0):.1f}")
        c2.metric("LLM avg (s)", f"{metrics.get('llm_latency_average_seconds', 0):.1f}")
        c3.metric("Prompt tokens", metrics.get("prompt_tokens", 0))
        c4.metric("Completion tokens", metrics.get("completion_tokens", 0))

        c5, c6, c7, c8 = st.columns(4)
        c5.metric(
            "RunPod avg (s)",
            f"{metrics.get('runpod_latency_average_seconds', 0):.1f}",
        )
        c6.metric(
            "R2 avg (s)",
            f"{metrics.get('r2_upload_latency_average_seconds', 0):.1f}",
        )
        c7.metric("Est. cost", f"{metrics.get('estimated_cost', 0):.4f}")
        c8.metric("Images", metrics.get("images_generated", 0))

        c9, c10, _, _ = st.columns(4)
        c9.metric("Total tokens", metrics.get("total_tokens", 0))
        c10.metric("Retries", metrics.get("retry_count", 0))

        st.json({k: v for k, v in metrics.items() if k != "raw"})


def render_images_section(images: list[dict[str, Any]]) -> None:
    """Render the generated-images expandable section."""
    with st.expander("Generated Images", expanded=False):
        if not images:
            st.info("No images yet.")
            return

        cols = st.columns(2)
        for index, image in enumerate(images):
            with cols[index % 2]:
                st.markdown(
                    f"**Scene {image.get('scene_id', '?')}:** "
                    f"{image.get('title', 'Untitled')}"
                )
                url = image.get("url") or ""
                if url:
                    st.image(url, use_container_width=True)
                else:
                    st.info(image.get("status", "Not generated yet"))


# ---------------------------------------------------------------------------
# App entry
# ---------------------------------------------------------------------------


def main() -> None:
    """Configure the page, run the pipeline on demand, and render results."""
    st.set_page_config(
        page_title="AI Director Studio",
        page_icon="🎬",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _init_session_state()

    render_header()
    topic, generate_clicked = render_topic_controls()

    if generate_clicked:
        if not topic:
            st.warning("Enter a historical topic before generating.")
        else:
            run_pipeline(topic)

    render_error_banner()
    st.divider()

    research, plan, storyboard, review, metrics, images = _result_payloads(
        st.session_state.get("pipeline_result")
    )

    render_research_section(research)
    render_director_section(plan)
    render_storyboard_section(storyboard)
    render_review_section(review)
    render_metrics_section(metrics)
    render_images_section(images)


if __name__ == "__main__":
    main()
