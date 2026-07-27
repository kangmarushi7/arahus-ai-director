"""Fast live verification: agents + first-scene image only."""

from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.api import build_pipeline
from src.domain.models import DomainType
from src.domain.service import DomainServiceError
from src.prompt import PromptComposer

CASES: list[tuple[str, DomainType]] = [
    ("The Fall of Constantinople", DomainType.HISTORY),
    ("Bitcoin ETF", DomainType.FINANCE),
    ("Life on Mars in 2150", DomainType.SCIFI),
]


@dataclass
class TopicReport:
    topic: str
    detected_domain: str
    confidence: float
    research: str
    director: str
    prompt: str
    image: str
    image_url: str
    notes: str = ""


def _pf(ok: bool) -> str:
    return "Pass" if ok else "Fail"


def _progress(update: object) -> None:
    message = getattr(update, "message", str(update))
    print(f"  · {message}")


def verify_topic(pipeline: object, topic: str, expected: DomainType) -> TopicReport:
    cleaned = " ".join(topic.split())
    notes: list[str] = []

    research_ok = False
    director_ok = False
    prompt_ok = False
    image_ok = False
    detected = "n/a"
    confidence = 0.0
    image_url = ""

    print(f"\n{'=' * 72}\nTOPIC: {cleaned}\n{'=' * 72}")

    # Domain
    try:
        domain_info = pipeline._domain_service.detect(cleaned)  # noqa: SLF001
        prompt_context = pipeline._domain_service.get_prompt_context(  # noqa: SLF001
            domain_info.domain
        )
    except (DomainServiceError, Exception) as exc:  # noqa: BLE001
        return TopicReport(
            topic=cleaned,
            detected_domain="error",
            confidence=0.0,
            research="Fail",
            director="Fail",
            prompt="Fail",
            image="Fail",
            image_url="",
            notes=f"domain detection failed: {exc}",
        )

    detected = domain_info.domain.value
    confidence = float(domain_info.confidence)
    domain_ok = domain_info.domain == expected
    print(f"Domain: {detected} (expected {expected.value}) conf={confidence:.2f}")
    print(f"Style: {prompt_context.style[:120]}")
    print(f"Camera: {prompt_context.camera[:120]}")
    print(f"Negative: {prompt_context.negative_prompt[:120]}")
    if not domain_ok:
        notes.append(f"domain mismatch expected={expected.value}")

    pipeline._reporter = None  # noqa: SLF001
    pipeline._bind_step_loggers()  # noqa: SLF001

    # Research
    try:
        research = pipeline._research_agent.run(  # noqa: SLF001
            cleaned, domain_info=domain_info
        )
        research_ok = bool(research.topic.strip()) and (
            bool(research.visual_details)
            or bool(research.key_people)
            or bool(research.location)
            or bool(research.important_events)
        )
        print(
            f"Research: people={len(research.key_people)} "
            f"events={len(research.important_events)} "
            f"visuals={len(research.visual_details)} "
            f"location={research.location!r}"
        )
    except Exception as exc:  # noqa: BLE001
        notes.append(f"research error: {exc}")
        traceback.print_exc()
        pipeline._unbind_step_loggers()  # noqa: SLF001
        return TopicReport(
            topic=cleaned,
            detected_domain=detected,
            confidence=confidence,
            research="Fail",
            director="Fail",
            prompt="Fail",
            image="Fail",
            image_url="",
            notes="; ".join(notes),
        )

    # Director
    try:
        plan = pipeline._director_agent.run(  # noqa: SLF001
            cleaned, research, domain_info=domain_info
        )
        director_ok = len(plan.scenes) == 4 and all(
            s.title.strip() and s.description.strip() for s in plan.scenes
        )
        print(f"Director scenes: {[s.title for s in plan.scenes]}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"director error: {exc}")
        traceback.print_exc()
        pipeline._unbind_step_loggers()  # noqa: SLF001
        return TopicReport(
            topic=cleaned,
            detected_domain=detected,
            confidence=confidence,
            research=_pf(research_ok),
            director="Fail",
            prompt="Fail",
            image="Fail",
            image_url="",
            notes="; ".join(notes),
        )

    # Prompt + Review (composer checks independent of review approval)
    storyboard = None
    try:
        storyboard = pipeline._prompt_agent.run(  # noqa: SLF001
            plan,
            research,
            domain_info=domain_info,
            prompt_context=prompt_context,
        )
    except Exception as exc:  # noqa: BLE001
        notes.append(f"prompt error: {exc}")
        traceback.print_exc()
        storyboard = None
        prompt_ok = False

    if storyboard is not None:
        try:
            review = pipeline._review_agent.run(storyboard)  # noqa: SLF001
            review_note = (
                f"review_approved={review.approved} score={review.overall_score:.0f}"
            )
            if not review.approved:
                notes.append(
                    f"review not approved (score={review.overall_score:.0f}) — "
                    "continuing with first-scene image"
                )
        except Exception as exc:  # noqa: BLE001
            review_note = f"review error: {exc}"
            notes.append(
                "review failed (rate limit/error) — continuing with composed storyboard"
            )
            print(f"Review skipped/failed: {exc}")

        style_token = prompt_context.style.split(",")[0].strip()
        camera_token = prompt_context.camera.split(",")[0].strip()
        neg_token = prompt_context.negative_prompt.split(",")[0].strip()
        first_prompt = storyboard.scenes[0].image_prompt or ""

        has_style = style_token in first_prompt
        has_camera = camera_token in first_prompt
        composed = PromptComposer().compose_from_domain(
            prompt_context,
            subject="verify",
            environment="verify",
            action="verify",
        )
        has_negative = neg_token.lower() in composed.negative_prompt.lower()
        well_formed = (
            len(first_prompt) > 40
            and "," in first_prompt
            and bool(first_prompt.strip())
        )
        prompt_ok = (
            has_style
            and has_camera
            and has_negative
            and well_formed
            and all(bool(s.image_prompt) for s in storyboard.scenes)
        )
        print(
            f"Prompt: {review_note} style={has_style} "
            f"camera={has_camera} negative={has_negative} well_formed={well_formed}"
        )
        print(f"Prompt[0] preview: {first_prompt[:220]}")
        if not has_style:
            notes.append("missing style pack in positive prompt")
        if not has_camera:
            notes.append("missing camera preset in positive prompt")
        if not has_negative:
            notes.append("missing negative prompt from domain YAML")
    else:
        prompt_ok = False
        review_note = "n/a"

    # First scene image only
    if storyboard is not None:
        scene0 = storyboard.scenes[0]
        print(f"Generating ONLY scene 1 image ({scene0.title!r})…")
        try:
            rendered, info = pipeline._render_scene_safe(scene0)  # noqa: SLF001
            image_url = info.url or ""
            image_ok = bool(image_url) and image_url.startswith("http")
            print(f"Image status={info.status!r} url={image_url!r}")
            if not image_ok:
                notes.append(f"image status={info.status}")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"image error: {exc}")
            traceback.print_exc()
            image_ok = False
    else:
        notes.append("skipped image (no storyboard)")

    pipeline._unbind_step_loggers()  # noqa: SLF001

    return TopicReport(
        topic=cleaned,
        detected_domain=detected,
        confidence=confidence,
        research=_pf(research_ok),
        director=_pf(director_ok),
        prompt=_pf(prompt_ok),
        image=_pf(image_ok),
        image_url=image_url or "—",
        notes="; ".join(notes),
    )


def main() -> int:
    pipeline = build_pipeline()
    reports: list[TopicReport] = []

    for topic, expected in CASES:
        reports.append(verify_topic(pipeline, topic, expected))

    print("\n" + "=" * 72)
    print("VERIFICATION REPORT")
    print("=" * 72)
    header = (
        f"{'Topic':<32} {'Domain':<10} {'Conf':>5} "
        f"{'Research':<8} {'Director':<8} {'Prompt':<8} {'Image':<8} URL"
    )
    print(header)
    print("-" * len(header))
    for r in reports:
        print(
            f"{r.topic:<32} {r.detected_domain:<10} {r.confidence:>5.2f} "
            f"{r.research:<8} {r.director:<8} {r.prompt:<8} {r.image:<8} "
            f"{r.image_url}"
        )
        if r.notes:
            print(f"  notes: {r.notes}")

    all_ok = all(
        r.detected_domain
        in {DomainType.HISTORY.value, DomainType.FINANCE.value, DomainType.SCIFI.value}
        and r.research == "Pass"
        and r.director == "Pass"
        and r.prompt == "Pass"
        and r.image == "Pass"
        for r in reports
    )
    # Also require exact expected domain mapping
    expected_map = {t: d.value for t, d in CASES}
    domain_ok = all(
        r.detected_domain == expected_map[r.topic] for r in reports
    )
    if all_ok and domain_ok:
        print("\nALL CHECKS PASSED")
        return 0
    print("\nSOME CHECKS FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
