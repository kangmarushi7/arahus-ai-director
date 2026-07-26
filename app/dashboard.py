"""AI Director Studio – Streamlit dashboard wired to DirectorPipeline."""

from __future__ import annotations

import time
import traceback
from typing import Any

import streamlit as st

from src.api import (
    build_prompt_playground,
    generate_pipeline_result,
    playground_image_model,
)
from src.config import reload_settings
from src.models.image import ImageResult
from src.models.pipeline import GeneratedImageInfo, PipelineResult
from src.pipeline import PipelineValidationError
from src.playground.persistence import (
    ensure_database,
    sync_pipeline_result,
    sync_storyboard_project,
)
from src.playground.prompt_playground import (
    PromptPlayground,
    PromptPlaygroundError,
    PromptVersionRecord,
)
from src.progress import ProgressReporter, ProgressUpdate, format_duration

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
        "console_logs": [],
        "stage_panel": ProgressReporter().format_stage_panel(),
        "pipeline_progress": 0.0,
        "pipeline_eta": None,
        "pipeline_elapsed": 0.0,
        "project_id": None,
        "scene_db_ids": {},
        "playground_compare": {},
        "playground_history": {},
        "scene_overrides": {},
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _apply_scene_overrides(
    storyboard: dict[str, Any],
    images: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Merge per-scene playground edits into storyboard/image payloads."""
    overrides: dict[Any, Any] = st.session_state.get("scene_overrides") or {}
    if not overrides:
        return storyboard, images

    scenes = []
    for scene in storyboard.get("scenes") or []:
        scene_id = int(scene.get("id") or 0)
        patch = overrides.get(scene_id) or overrides.get(str(scene_id))
        if not patch:
            scenes.append(scene)
            continue
        updated = dict(scene)
        if patch.get("prompt") is not None:
            updated["image_prompt"] = patch["prompt"]
        if patch.get("url") is not None:
            image = dict(updated.get("image") or {})
            image["url"] = patch["url"]
            image["prompt"] = patch.get("prompt") or updated.get("image_prompt")
            updated["image"] = image
        scenes.append(updated)
    storyboard = {**storyboard, "scenes": scenes}

    image_rows = [dict(item) for item in images]
    by_id = {str(item.get("scene_id")): item for item in image_rows}
    for scene_id, patch in overrides.items():
        key = str(scene_id)
        row = by_id.get(key)
        if row is None:
            continue
        if patch.get("prompt") is not None:
            row["prompt"] = patch["prompt"]
        if "url" in patch:
            row["url"] = patch.get("url") or ""
        if patch.get("status") is not None:
            row["status"] = patch["status"]
    return storyboard, image_rows


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
        storyboard, images = _apply_scene_overrides(
            PLACEHOLDER_STORYBOARD,
            PLACEHOLDER_IMAGES,
        )
        return (
            PLACEHOLDER_RESEARCH,
            PLACEHOLDER_DIRECTOR,
            storyboard,
            PLACEHOLDER_REVIEW,
            PLACEHOLDER_METRICS,
            images,
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
    storyboard, images = _apply_scene_overrides(
        result.storyboard.model_dump(mode="json"),
        images,
    )
    return (
        result.research.model_dump(mode="json"),
        result.plan.model_dump(mode="json"),
        storyboard,
        result.review.model_dump(mode="json"),
        result.metrics,
        images,
    )


def run_pipeline(topic: str, widgets: dict[str, Any]) -> None:
    """Execute DirectorPipeline and store intermediates in session state.

    Exceptions are captured into session state so the Streamlit UI never crashes.
    Progress lines, stage bars, and ETA stream into ``widgets`` while running.
    """
    st.session_state["last_error"] = None
    st.session_state["last_topic"] = topic
    st.session_state["console_logs"] = []
    st.session_state["stage_panel"] = ProgressReporter().format_stage_panel()
    st.session_state["pipeline_progress"] = 0.0
    st.session_state["pipeline_eta"] = None
    st.session_state["pipeline_elapsed"] = 0.0

    tracker = ProgressReporter()
    log_placeholder = widgets["log"]
    stage_placeholder = widgets["stages"]
    progress_bar = widgets["progress"]
    meta_box = widgets["meta"]

    def _render_progress_ui() -> None:
        logs = st.session_state.get("console_logs") or []
        fraction = float(st.session_state.get("pipeline_progress") or 0.0)
        elapsed = float(st.session_state.get("pipeline_elapsed") or 0.0)
        eta = st.session_state.get("pipeline_eta")
        stage_panel = st.session_state.get("stage_panel") or ""
        progress_bar.progress(min(max(fraction, 0.0), 1.0))
        meta_box.markdown(
            f"**{fraction * 100:.0f}%** complete · "
            f"elapsed {format_duration(elapsed)} · "
            f"ETA {format_duration(eta)}"
        )
        stage_placeholder.code(stage_panel, language="text")
        log_placeholder.code(
            "\n".join(logs) if logs else "Waiting for pipeline events…",
            language="text",
        )

    def on_progress(update: ProgressUpdate) -> None:
        tracker.fraction = max(tracker.fraction, float(update.fraction or 0.0))
        st.session_state["console_logs"].append(update.message)
        st.session_state["stage_panel"] = update.stage_panel
        st.session_state["pipeline_progress"] = tracker.fraction
        st.session_state["pipeline_elapsed"] = time.perf_counter() - tracker.started_at
        st.session_state["pipeline_eta"] = tracker.eta_seconds()
        _render_progress_ui()

    _render_progress_ui()

    try:
        reload_settings()
        with st.status(
            f"Directing “{topic}”… this can take several minutes",
            expanded=True,
        ) as status:
            result = generate_pipeline_result(topic, progress_callback=on_progress)
            status.update(label=f"Pipeline completed for “{topic}”", state="complete")
        st.session_state["pipeline_result"] = result
        st.session_state["scene_overrides"] = {}
        # Refresh editable prompt boxes from the new storyboard.
        for scene in result.storyboard.scenes:
            st.session_state[f"playground_prompt_{scene.id}"] = (
                scene.image_prompt or scene.description
            )
        st.session_state["pipeline_progress"] = 1.0
        st.session_state["pipeline_eta"] = 0.0
        st.session_state["pipeline_elapsed"] = time.perf_counter() - tracker.started_at
        try:
            project_id, mapping = sync_pipeline_result(
                result,
                project_id=st.session_state.get("project_id"),
                image_model=playground_image_model(),
            )
            st.session_state["project_id"] = project_id
            st.session_state["scene_db_ids"] = mapping
        except Exception as sync_exc:  # noqa: BLE001 - playground still usable later
            st.warning(f"Could not sync storyboard to database: {sync_exc}")
        _render_progress_ui()
        st.success(f"Pipeline completed for **{topic}**.")
    except PipelineValidationError as exc:
        st.session_state["pipeline_result"] = None
        on_progress(
            ProgressUpdate(
                message=f"ERROR: Storyboard rejected after review retries — {exc}",
                fraction=tracker.fraction,
                stage_panel=st.session_state.get("stage_panel") or "",
                stages={},
            )
        )
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
        on_progress(
            ProgressUpdate(
                message=f"ERROR: {type(exc).__name__}: {exc}",
                fraction=tracker.fraction,
                stage_panel=st.session_state.get("stage_panel") or "",
                stages={},
            )
        )
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


def render_live_console() -> dict[str, Any]:
    """Render Live Console widgets and return updatable placeholders."""
    logs: list[str] = st.session_state.get("console_logs") or []
    fraction = float(st.session_state.get("pipeline_progress") or 0.0)
    elapsed = float(st.session_state.get("pipeline_elapsed") or 0.0)
    eta = st.session_state.get("pipeline_eta")
    stage_panel = (
        st.session_state.get("stage_panel")
        or ProgressReporter().format_stage_panel()
    )

    with st.expander("Live Console", expanded=True):
        meta_box = st.empty()
        progress_bar = st.progress(min(max(fraction, 0.0), 1.0))
        meta_box.markdown(
            f"**{fraction * 100:.0f}%** complete · "
            f"elapsed {format_duration(elapsed)} · "
            f"ETA {format_duration(eta)}"
        )
        st.caption("Stage progress")
        stage_placeholder = st.empty()
        stage_placeholder.code(stage_panel, language="text")
        st.caption("Activity log")
        log_placeholder = st.empty()
        if logs:
            log_placeholder.code("\n".join(logs), language="text")
        else:
            log_placeholder.caption(
                "Every agent/LLM step streams here when you click Generate "
                "(research → director → prompt/review → images)."
            )
    return {
        "log": log_placeholder,
        "stages": stage_placeholder,
        "progress": progress_bar,
        "meta": meta_box,
    }


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
# Prompt playground (per-scene edit / generate / compare)
# ---------------------------------------------------------------------------


def _ensure_scene_mapping(storyboard: dict[str, Any]) -> dict[int, int]:
    """Ensure DB project/scenes exist for the current storyboard."""
    mapping = {
        int(key): int(value)
        for key, value in (st.session_state.get("scene_db_ids") or {}).items()
    }
    scenes = storyboard.get("scenes") or []
    needed = {int(scene.get("id")) for scene in scenes if scene.get("id")}
    if needed and needed.issubset(set(mapping)):
        return mapping

    ensure_database()
    project_id, mapping = sync_storyboard_project(
        str(storyboard.get("topic") or st.session_state.get("last_topic") or "Untitled"),
        scenes,
        project_id=st.session_state.get("project_id"),
        image_model=playground_image_model(),
    )
    st.session_state["project_id"] = project_id
    st.session_state["scene_db_ids"] = mapping
    return mapping


def _update_local_scene_prompt(storyboard_scene_id: int, prompt: str) -> None:
    """Update only one scene prompt in session overrides / pipeline result."""
    overrides = dict(st.session_state.get("scene_overrides") or {})
    patch = dict(overrides.get(storyboard_scene_id) or {})
    patch["prompt"] = prompt
    overrides[storyboard_scene_id] = patch
    st.session_state["scene_overrides"] = overrides

    result: PipelineResult | None = st.session_state.get("pipeline_result")
    if result is None:
        return

    updated_scenes = []
    for scene in result.storyboard.scenes:
        if scene.id == storyboard_scene_id:
            updated_scenes.append(scene.model_copy(update={"image_prompt": prompt}))
        else:
            updated_scenes.append(scene)
    storyboard = result.storyboard.model_copy(update={"scenes": updated_scenes})
    st.session_state["pipeline_result"] = result.model_copy(update={"storyboard": storyboard})


def _update_local_scene_image(
    storyboard_scene_id: int,
    *,
    prompt: str,
    url: str | None,
    status: str,
) -> None:
    """Patch only one scene's image fields in overrides / pipeline result."""
    overrides = dict(st.session_state.get("scene_overrides") or {})
    overrides[storyboard_scene_id] = {
        "prompt": prompt,
        "url": url,
        "status": status,
    }
    st.session_state["scene_overrides"] = overrides

    result: PipelineResult | None = st.session_state.get("pipeline_result")
    if result is None:
        return

    image_result = ImageResult(prompt=prompt, url=url) if url or prompt else None
    updated_scenes = []
    for scene in result.storyboard.scenes:
        if scene.id == storyboard_scene_id:
            updated_scenes.append(
                scene.model_copy(
                    update={
                        "image_prompt": prompt,
                        "image": image_result,
                        "error": None if url else scene.error,
                    }
                )
            )
        else:
            updated_scenes.append(scene)

    images: list[GeneratedImageInfo] = []
    replaced = False
    for item in result.images:
        if item.scene_id == storyboard_scene_id:
            images.append(
                item.model_copy(
                    update={
                        "prompt": prompt,
                        "url": url,
                        "status": status,
                    }
                )
            )
            replaced = True
        else:
            images.append(item)
    if not replaced:
        title = next(
            (scene.title for scene in updated_scenes if scene.id == storyboard_scene_id),
            f"Scene {storyboard_scene_id}",
        )
        images.append(
            GeneratedImageInfo(
                scene_id=storyboard_scene_id,
                title=title,
                prompt=prompt,
                url=url,
                status=status,
            )
        )

    storyboard = result.storyboard.model_copy(update={"scenes": updated_scenes})
    st.session_state["pipeline_result"] = result.model_copy(
        update={"storyboard": storyboard, "images": images}
    )


def _selected_image_url(version: PromptVersionRecord) -> str | None:
    for image in reversed(version.images):
        if image.url:
            return image.url
    return None


def _render_version_card(
    version: PromptVersionRecord,
    *,
    playground: PromptPlayground,
    storyboard_scene_id: int,
    key_prefix: str,
) -> None:
    """Render one prompt version with select action and preview image."""
    badge = "✓ selected" if version.is_selected else "version"
    container = st.container(border=True)
    with container:
        st.markdown(
            f"**v{version.version}** · {badge} · `{version.model}` · "
            f"id={version.id}"
        )
        st.code(version.prompt, language=None)
        url = _selected_image_url(version)
        if url:
            st.image(url, use_container_width=True)
        elif version.images:
            latest = version.images[-1]
            st.caption(f"Image status: {latest.status}")
            if latest.error:
                st.error(latest.error)
        else:
            st.caption("No image for this version yet.")

        if st.button(
            "Select this version",
            key=f"{key_prefix}_select_{version.id}",
            disabled=version.is_selected,
        ):
            selected = playground.select_version(version.id)
            _update_local_scene_prompt(storyboard_scene_id, selected.prompt)
            url = _selected_image_url(selected)
            _update_local_scene_image(
                storyboard_scene_id,
                prompt=selected.prompt,
                url=url,
                status="ok" if url else "Selected (no image)",
            )
            st.success(f"Selected v{selected.version} for scene {storyboard_scene_id}.")
            st.rerun()


def render_prompt_playground_section(storyboard: dict[str, Any]) -> None:
    """Per-scene prompt editor: Save / Generate / Compare / Version History."""
    with st.expander("Prompt Playground", expanded=True):
        st.caption(
            "Edit one scene at a time. Generate creates a new PromptVersion and "
            "image for that scene only — the rest of the storyboard is unchanged."
        )
        scenes = storyboard.get("scenes") or []
        if not scenes:
            st.info("No scenes available yet. Run Generate on a topic first.")
            return

        try:
            mapping = _ensure_scene_mapping(storyboard)
            playground = build_prompt_playground()
            model_name = playground_image_model()
        except Exception as exc:  # noqa: BLE001 - keep studio alive
            st.error(f"Prompt playground unavailable: {exc}")
            return

        compare_state: dict[Any, bool] = st.session_state.setdefault(
            "playground_compare", {}
        )
        history_state: dict[Any, bool] = st.session_state.setdefault(
            "playground_history", {}
        )

        for scene in scenes:
            storyboard_scene_id = int(scene.get("id") or 0)
            if storyboard_scene_id < 1:
                continue
            db_scene_id = mapping.get(storyboard_scene_id)
            if db_scene_id is None:
                st.warning(f"Scene {storyboard_scene_id} is not synced to the database.")
                continue

            title = scene.get("title") or f"Scene {storyboard_scene_id}"
            st.markdown(f"### Scene {storyboard_scene_id}: {title}")
            st.write(scene.get("description") or "")

            prompt_key = f"playground_prompt_{storyboard_scene_id}"
            default_prompt = str(scene.get("image_prompt") or scene.get("description") or "")
            if prompt_key not in st.session_state:
                st.session_state[prompt_key] = default_prompt

            st.text_area(
                "Editable prompt",
                key=prompt_key,
                height=120,
                label_visibility="collapsed",
                placeholder="Write or refine the SDXL image prompt for this scene…",
            )

            c1, c2, c3, c4 = st.columns(4)
            save_clicked = c1.button("Save", key=f"pg_save_{storyboard_scene_id}")
            generate_clicked = c2.button(
                "Generate",
                type="primary",
                key=f"pg_generate_{storyboard_scene_id}",
            )
            compare_clicked = c3.button(
                "Compare",
                key=f"pg_compare_{storyboard_scene_id}",
            )
            history_clicked = c4.button(
                "Version History",
                key=f"pg_history_{storyboard_scene_id}",
            )

            if compare_clicked:
                compare_state[storyboard_scene_id] = not compare_state.get(
                    storyboard_scene_id, False
                )
            if history_clicked:
                history_state[storyboard_scene_id] = not history_state.get(
                    storyboard_scene_id, False
                )

            edited_prompt = str(st.session_state.get(prompt_key) or "").strip()

            if save_clicked:
                if not edited_prompt:
                    st.warning("Enter a prompt before saving.")
                else:
                    try:
                        version = playground.create_prompt_version(
                            db_scene_id,
                            edited_prompt,
                            model_name,
                        )
                        playground.select_version(version.id)
                        _update_local_scene_prompt(storyboard_scene_id, edited_prompt)
                        st.success(
                            f"Saved prompt as v{version.version} "
                            f"(scene {storyboard_scene_id} only)."
                        )
                        st.rerun()
                    except (PromptPlaygroundError, ValueError) as exc:
                        st.error(f"Save failed: {exc}")

            if generate_clicked:
                if not edited_prompt:
                    st.warning("Enter a prompt before generating.")
                else:
                    try:
                        with st.spinner(
                            f"Generating image for scene {storyboard_scene_id} only…"
                        ):
                            version = playground.create_prompt_version(
                                db_scene_id,
                                edited_prompt,
                                model_name,
                            )
                            image = playground.generate_image(version.id)
                            playground.select_version(version.id)
                        _update_local_scene_image(
                            storyboard_scene_id,
                            prompt=edited_prompt,
                            url=image.url,
                            status=image.status,
                        )
                        if image.url:
                            st.success(
                                f"Generated image for scene {storyboard_scene_id} "
                                f"(v{version.version})."
                            )
                        else:
                            st.warning(
                                f"Scene {storyboard_scene_id} v{version.version}: "
                                f"{image.status}"
                                + (f" — {image.error}" if image.error else "")
                            )
                        st.rerun()
                    except (PromptPlaygroundError, ValueError) as exc:
                        st.error(f"Generate failed: {exc}")

            try:
                versions = playground.list_versions(db_scene_id)
            except PromptPlaygroundError as exc:
                st.error(f"Could not load versions: {exc}")
                versions = []

            selected = next((item for item in versions if item.is_selected), None)
            if selected and _selected_image_url(selected):
                st.image(_selected_image_url(selected), use_container_width=True)
            elif selected:
                st.caption("Selected version has no image yet.")

            st.markdown("**Prompt versions**")
            if not versions:
                st.caption("No prompt versions yet — Save or Generate to create one.")
            else:
                for version in reversed(versions):
                    # Compact always-visible list; detailed cards when History is open.
                    if history_state.get(storyboard_scene_id):
                        _render_version_card(
                            version,
                            playground=playground,
                            storyboard_scene_id=storyboard_scene_id,
                            key_prefix=f"hist_{storyboard_scene_id}",
                        )
                    else:
                        label = f"v{version.version}"
                        if version.is_selected:
                            label = f"✅ {label} (selected)"
                        cols = st.columns([3, 1])
                        with cols[0]:
                            st.markdown(f"**{label}** · `{version.model}`")
                            st.caption(version.prompt[:160] + ("…" if len(version.prompt) > 160 else ""))
                        with cols[1]:
                            if st.button(
                                "Select",
                                key=f"list_select_{storyboard_scene_id}_{version.id}",
                                disabled=version.is_selected,
                            ):
                                chosen = playground.select_version(version.id)
                                st.session_state[prompt_key] = chosen.prompt
                                _update_local_scene_prompt(
                                    storyboard_scene_id,
                                    chosen.prompt,
                                )
                                url = _selected_image_url(chosen)
                                _update_local_scene_image(
                                    storyboard_scene_id,
                                    prompt=chosen.prompt,
                                    url=url,
                                    status="ok" if url else "Selected (no image)",
                                )
                                st.rerun()

            if compare_state.get(storyboard_scene_id) and versions:
                st.markdown("**Compare versions**")
                cols = st.columns(min(3, len(versions)))
                for index, version in enumerate(reversed(versions[-3:])):
                    with cols[index % len(cols)]:
                        label = f"v{version.version}"
                        if version.is_selected:
                            label += " (selected)"
                        st.markdown(f"**{label}**")
                        st.code(version.prompt, language=None)
                        url = _selected_image_url(version)
                        if url:
                            st.image(url, use_container_width=True)
                        else:
                            st.caption("No image")
                        if st.button(
                            "Select",
                            key=f"cmp_select_{storyboard_scene_id}_{version.id}",
                            disabled=version.is_selected,
                        ):
                            selected = playground.select_version(version.id)
                            _update_local_scene_prompt(
                                storyboard_scene_id,
                                selected.prompt,
                            )
                            st.session_state[prompt_key] = selected.prompt
                            url = _selected_image_url(selected)
                            _update_local_scene_image(
                                storyboard_scene_id,
                                prompt=selected.prompt,
                                url=url,
                                status="ok" if url else "Selected (no image)",
                            )
                            st.rerun()

            st.divider()


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
    console_widgets = render_live_console()

    if generate_clicked:
        if not topic:
            st.warning("Enter a historical topic before generating.")
        else:
            run_pipeline(topic, console_widgets)

    render_error_banner()
    st.divider()

    research, plan, storyboard, review, metrics, images = _result_payloads(
        st.session_state.get("pipeline_result")
    )

    render_research_section(research)
    render_director_section(plan)
    render_storyboard_section(storyboard)
    render_prompt_playground_section(storyboard)
    render_review_section(review)
    render_metrics_section(metrics)
    render_images_section(images)


if __name__ == "__main__":
    main()
