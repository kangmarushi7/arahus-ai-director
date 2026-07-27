"""RunPod Serverless worker for FLUX.1 [dev] text-to-image generation."""

from __future__ import annotations

import os
from typing import Any

import runpod
import torch
from diffusers import FluxPipeline

from src.services.r2 import upload_image

# Model is loaded once at cold start and reused across jobs.
MODEL_ID = os.environ.get("IMAGE_MODEL_ID", "black-forest-labs/FLUX.1-dev").strip()
DEFAULT_NUM_IMAGES = 1
DEFAULT_WIDTH = 1024
DEFAULT_HEIGHT = 1024
DEFAULT_NUM_INFERENCE_STEPS = 28
DEFAULT_GUIDANCE_SCALE = 3.5
DEFAULT_MAX_SEQUENCE_LENGTH = 512

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
# FLUX.1-dev is trained / shipped for bfloat16 on modern NVIDIA GPUs.
DTYPE = torch.bfloat16 if DEVICE == "cuda" else torch.float32
CPU_OFFLOAD = os.environ.get("FLUX_CPU_OFFLOAD", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

_hf_token = (
    os.environ.get("HF_TOKEN")
    or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    or None
)

print(f"Loading {MODEL_ID} on {DEVICE} ({DTYPE})")
pipe = FluxPipeline.from_pretrained(
    MODEL_ID,
    torch_dtype=DTYPE,
    token=_hf_token,
)
if DEVICE == "cuda":
    if CPU_OFFLOAD:
        pipe.enable_model_cpu_offload()
    else:
        pipe.to(DEVICE)
else:
    pipe.to(DEVICE)
print("Model ready")


def _positive_int(value: object, *, default: int, field: str) -> int | dict[str, str]:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return {"error": f"{field} must be a positive integer"}
    return value


def _positive_float(
    value: object,
    *,
    default: float,
    field: str,
) -> float | dict[str, str]:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < 0:
        return {"error": f"{field} must be a non-negative number"}
    return float(value)


def handler(job: dict[str, Any]) -> dict[str, Any]:
    """Generate N images and return public Cloudflare R2 URLs."""
    job_input = job.get("input") or {}
    prompt = job_input.get("prompt")
    num_images = job_input.get("num_images", DEFAULT_NUM_IMAGES)

    if not isinstance(prompt, str) or not prompt.strip():
        return {"error": "Missing required input field: prompt"}

    if not isinstance(num_images, int) or num_images < 1:
        return {"error": "num_images must be a positive integer"}

    width = _positive_int(
        job_input.get("width"),
        default=DEFAULT_WIDTH,
        field="width",
    )
    if isinstance(width, dict):
        return width

    height = _positive_int(
        job_input.get("height"),
        default=DEFAULT_HEIGHT,
        field="height",
    )
    if isinstance(height, dict):
        return height

    steps = _positive_int(
        job_input.get("num_inference_steps", job_input.get("steps")),
        default=DEFAULT_NUM_INFERENCE_STEPS,
        field="num_inference_steps",
    )
    if isinstance(steps, dict):
        return steps

    guidance = _positive_float(
        job_input.get("guidance_scale"),
        default=DEFAULT_GUIDANCE_SCALE,
        field="guidance_scale",
    )
    if isinstance(guidance, dict):
        return guidance

    seed = job_input.get("seed")
    generator = None
    if seed is not None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            return {"error": "seed must be an integer when provided"}
        generator = torch.Generator(device="cpu").manual_seed(seed)

    images: list[str] = []
    cleaned_prompt = prompt.strip()

    for _ in range(num_images):
        image = pipe(
            prompt=cleaned_prompt,
            height=height,
            width=width,
            num_inference_steps=steps,
            guidance_scale=guidance,
            max_sequence_length=DEFAULT_MAX_SEQUENCE_LENGTH,
            generator=generator,
        ).images[0]

        url = upload_image(image)
        images.append(url)

    return {"images": images}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
