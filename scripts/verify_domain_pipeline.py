"""Live verification of domain-aware pipeline for three topics."""

from __future__ import annotations

import sys
import traceback

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.api import build_pipeline
from src.domain.models import DomainType
from src.models.storyboard import DirectorPlan

CASES: list[tuple[str, DomainType]] = [
    ("The Fall of Constantinople", DomainType.HISTORY),
    ("Bitcoin ETF", DomainType.FINANCE),
    ("Life on Mars in 2150", DomainType.SCIFI),
]


def _progress(update: object) -> None:
    message = getattr(update, "message", str(update))
    print(f"  · {message}")


def main() -> int:
    pipeline = build_pipeline()
    # Keep review loop short for live verification.
    pipeline._max_storyboard_retries = 0  # noqa: SLF001 - verification harness

    failures: list[str] = []
    results: list[dict[str, object]] = []

    for topic, expected in CASES:
        print("\n" + "=" * 72)
        print(f"TOPIC: {topic}")
        print("=" * 72)
        try:
            result = pipeline.generate(topic, progress_callback=_progress)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            failures.append(f"{topic}: pipeline failed: {exc}")
            continue

        domain = result.domain_info.domain if result.domain_info else None
        prompt_ctx = result.prompt_context
        print("\n--- Verification ---")
        print(f"detected_domain={domain.value if domain else None} expected={expected.value}")
        print(f"confidence={result.domain_info.confidence if result.domain_info else None}")
        if prompt_ctx:
            print(f"style_pack={prompt_ctx.style[:140]}")
            print(f"camera_preset={prompt_ctx.camera[:140]}")

        # 1) Domain detection
        if domain != expected:
            failures.append(
                f"{topic}: domain={domain} expected={expected}"
            )

        # 2) Research adapts — prompt path embeds domain; check research populated
        research = result.research
        if not research.topic.strip():
            failures.append(f"{topic}: empty research topic")
        print(
            f"research: location={research.location!r} "
            f"people={len(research.key_people)} visuals={len(research.visual_details)}"
        )

        # 3) Director adapts — plan has 4 scenes
        plan: DirectorPlan = result.plan
        if len(plan.scenes) != 4:
            failures.append(f"{topic}: expected 4 scenes, got {len(plan.scenes)}")
        print(f"director scenes: {[s.title for s in plan.scenes]}")

        # 4) Prompt style pack
        if prompt_ctx is None:
            failures.append(f"{topic}: missing prompt_context")
        else:
            style_token = prompt_ctx.style.split(",")[0].strip()
            camera_token = prompt_ctx.camera.split(",")[0].strip()
            for scene in result.storyboard.scenes:
                prompt = scene.image_prompt or ""
                if style_token and style_token not in prompt:
                    failures.append(
                        f"{topic} scene {scene.id}: missing style token {style_token!r}"
                    )
                if camera_token and camera_token not in prompt:
                    failures.append(
                        f"{topic} scene {scene.id}: missing camera token {camera_token!r}"
                    )
            print(
                f"prompt[0] chars={len(result.storyboard.scenes[0].image_prompt or '')} "
                f"contains_style={style_token in (result.storyboard.scenes[0].image_prompt or '')} "
                f"contains_camera={camera_token in (result.storyboard.scenes[0].image_prompt or '')}"
            )
            print(f"prompt[0] preview={(result.storyboard.scenes[0].image_prompt or '')[:220]}")

        # 5) Image generation
        ok_urls = sum(1 for img in result.images if img.url)
        failed = [img for img in result.images if not img.url]
        print(f"images: {ok_urls}/{len(result.images)} with URLs")
        for img in result.images:
            print(f"  scene {img.scene_id}: status={img.status!r} url={img.url!r}")
        if ok_urls < 1:
            failures.append(f"{topic}: no successful image URLs ({len(failed)} failures)")

        results.append(
            {
                "topic": topic,
                "domain": domain.value if domain else None,
                "expected": expected.value,
                "images_ok": ok_urls,
            }
        )

    print("\n" + "=" * 72)
    print("SUMMARY")
    for row in results:
        print(row)
    if failures:
        print("FAILURES:")
        for item in failures:
            print(f" - {item}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
