"""Arahus Lab — simple end-to-end pipeline test dashboard (Railway-ready)."""

from __future__ import annotations

import os
import time
import traceback
from typing import Any

import streamlit as st

from src.api import generate_pipeline_result
from src.config import get_settings, reload_settings
from src.models.pipeline import PipelineResult
from src.pipeline import PipelineValidationError
from src.progress import ProgressReporter, ProgressUpdate, format_duration

SAMPLE_TOPICS = [
    "Fall of Constantinople",
    "Apollo 11 moon landing",
    "A cyberpunk street market at night",
    "Quarterly earnings board meeting",
]


def _init_state() -> None:
    defaults: dict[str, Any] = {
        "lab_logs": [],
        "lab_progress": 0.0,
        "lab_elapsed": 0.0,
        "lab_eta": None,
        "lab_stage_panel": ProgressReporter().format_stage_panel(),
        "lab_result": None,
        "lab_error": None,
        "lab_topic": SAMPLE_TOPICS[0],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _config_status() -> dict[str, bool]:
    """Return which integrations are configured (no secret values)."""
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
    }


def _run_pipeline(topic: str) -> None:
    st.session_state["lab_error"] = None
    st.session_state["lab_logs"] = []
    st.session_state["lab_progress"] = 0.0
    st.session_state["lab_eta"] = None
    st.session_state["lab_elapsed"] = 0.0
    st.session_state["lab_stage_panel"] = ProgressReporter().format_stage_panel()
    st.session_state["lab_topic"] = topic

    tracker = ProgressReporter()
    log_box = st.empty()
    stage_box = st.empty()
    progress_bar = st.progress(0.0)
    meta_box = st.empty()

    def _paint() -> None:
        logs = st.session_state.get("lab_logs") or []
        fraction = float(st.session_state.get("lab_progress") or 0.0)
        elapsed = float(st.session_state.get("lab_elapsed") or 0.0)
        eta = st.session_state.get("lab_eta")
        progress_bar.progress(min(max(fraction, 0.0), 1.0))
        meta_box.markdown(
            f"**{fraction * 100:.0f}%** · elapsed {format_duration(elapsed)} · "
            f"ETA {format_duration(eta)}"
        )
        stage_box.code(
            st.session_state.get("lab_stage_panel") or "",
            language="text",
        )
        log_box.code("\n".join(logs[-80:]) if logs else "Waiting…", language="text")

    def on_progress(update: ProgressUpdate) -> None:
        tracker.fraction = max(tracker.fraction, float(update.fraction or 0.0))
        st.session_state["lab_logs"].append(update.message)
        st.session_state["lab_stage_panel"] = update.stage_panel
        st.session_state["lab_progress"] = tracker.fraction
        st.session_state["lab_elapsed"] = time.perf_counter() - tracker.started_at
        st.session_state["lab_eta"] = tracker.eta_seconds()
        _paint()

    _paint()
    try:
        reload_settings()
        result = generate_pipeline_result(topic, progress_callback=on_progress)
        st.session_state["lab_result"] = result
        st.session_state["lab_progress"] = 1.0
        st.session_state["lab_elapsed"] = time.perf_counter() - tracker.started_at
        st.session_state["lab_eta"] = 0.0
        _paint()
        st.success(f"Pipeline finished for “{topic}”.")
    except PipelineValidationError as exc:
        st.session_state["lab_result"] = None
        st.session_state["lab_error"] = {
            "type": "PipelineValidationError",
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        st.error(f"Storyboard rejected: {exc}")
    except Exception as exc:  # noqa: BLE001 - surface to lab UI
        st.session_state["lab_result"] = None
        st.session_state["lab_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        st.error(f"{type(exc).__name__}: {exc}")


def _render_result(result: PipelineResult) -> None:
    if result.using_stub_services:
        st.warning(
            "Stub image/storage services were used — image URLs may be missing. "
            "Set RUNPOD_* and R2_* for real renders."
        )

    domain = result.domain_info
    if domain is not None:
        st.subheader("Domain")
        st.write(
            f"**{domain.domain.value}** · confidence {domain.confidence:.2f} · "
            f"{domain.reasoning}"
        )

    if result.character_bible:
        with st.expander("Character bible", expanded=False):
            st.code(result.character_bible, language="text")

    with st.expander("Research", expanded=True):
        research = result.research
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**Period:** {research.time_period or '—'}")
            st.markdown(f"**Location:** {research.location or '—'}")
            st.markdown("**Key people**")
            st.write(research.key_people or [])
        with c2:
            st.markdown("**Events**")
            st.write(research.important_events or [])
            st.markdown("**Notes**")
            st.write(research.historical_notes or [])

    with st.expander("Director plan", expanded=True):
        for scene in result.plan.scenes:
            st.markdown(f"**Scene {scene.id}: {scene.title}**")
            st.write(scene.description)

    with st.expander("Storyboard prompts", expanded=True):
        for scene in result.storyboard.scenes:
            st.markdown(f"**Scene {scene.id}: {scene.title}**")
            st.code(scene.image_prompt or scene.description, language=None)

    with st.expander("Review", expanded=True):
        review = result.review
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Overall", f"{review.overall_score:.0f}")
        m2.metric("Domain", f"{review.domain_accuracy:.0f}")
        m3.metric("Visual", f"{review.visual_quality:.0f}")
        m4.metric("Continuity", f"{review.scene_continuity:.0f}")
        m5.metric("Prompts", f"{review.prompt_quality:.0f}")
        st.write(f"**Approved:** {'Yes' if review.approved else 'No'}")
        if review.issues:
            st.markdown("**Issues**")
            st.write(review.issues)
        if review.recommendations:
            st.markdown("**Recommendations**")
            st.write(review.recommendations)

    with st.expander("Images", expanded=True):
        if not result.images:
            st.caption("No images produced.")
        for item in result.images:
            st.markdown(f"**Scene {item.scene_id}: {item.title}** — {item.status}")
            if item.url:
                st.image(item.url, use_container_width=True)
            else:
                st.caption("No public URL")

    with st.expander("Metrics / profiler", expanded=False):
        metrics = result.metrics or {}
        report = metrics.get("pipeline_report") or metrics.get("profiler") or metrics
        st.json(report)


def main() -> None:
    st.set_page_config(
        page_title="Arahus Lab",
        page_icon="🎬",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _init_state()

    st.title("Arahus Lab")
    st.caption("End-to-end pipeline test console — domain → research → images.")

    status = _config_status()
    with st.sidebar:
        st.header("Service status")
        st.write(f"OpenRouter LLM: {'ready' if status['llm'] else 'missing key'}")
        st.write(f"RunPod images: {'ready' if status['runpod'] else 'not configured'}")
        st.write(f"Cloudflare R2: {'ready' if status['r2'] else 'not configured'}")
        st.write(f"Database: {'ready' if status['database'] else 'optional / unset'}")
        st.write(
            f"ALLOW_STUB_SERVICES: {'on' if status['allow_stubs'] else 'off'}"
        )
        if not status["llm"]:
            st.error("Set OPENROUTER_API_KEY to run the pipeline.")
        if not status["runpod"] or not status["r2"]:
            if status["allow_stubs"]:
                st.warning("Images will use stubs (no real renders).")
            else:
                st.error(
                    "Set RUNPOD_* + R2_* or enable ALLOW_STUB_SERVICES=true "
                    "for LLM-only dry runs."
                )
        st.divider()
        st.caption(f"PORT={os.environ.get('PORT', '8501')}")
        st.caption("Hosted for Railway / any VPS.")

    topic = st.text_input(
        "Topic",
        value=st.session_state.get("lab_topic", SAMPLE_TOPICS[0]),
        placeholder="e.g. Fall of Constantinople",
    )
    cols = st.columns([1, 3])
    with cols[0]:
        run_clicked = st.button("Run pipeline", type="primary", use_container_width=True)
    with cols[1]:
        pick = st.selectbox("Sample topics", SAMPLE_TOPICS, index=0)
        if st.button("Use sample", use_container_width=False):
            st.session_state["lab_topic"] = pick
            st.rerun()

    st.subheader("Live run")
    if run_clicked:
        cleaned = " ".join(topic.split())
        if not cleaned:
            st.warning("Enter a topic first.")
        elif not status["llm"]:
            st.error("Cannot start: OPENROUTER_API_KEY is missing.")
        else:
            _run_pipeline(cleaned)

    if st.session_state.get("lab_error"):
        with st.expander("Last error", expanded=True):
            st.json(st.session_state["lab_error"])

    result = st.session_state.get("lab_result")
    if isinstance(result, PipelineResult):
        st.divider()
        st.header("Results")
        _render_result(result)
    elif not run_clicked:
        st.info("Enter a topic and click **Run pipeline** to test end-to-end.")


if __name__ == "__main__":
    main()
