"""RunPod Serverless worker for SDXL-Turbo text-to-image generation."""

from __future__ import annotations

from typing import Any

import runpod
import torch
from diffusers import AutoPipelineForText2Image

from src.services.r2 import upload_image

# Model is loaded once at cold start and reused across jobs.
MODEL_ID = "stabilityai/sdxl-turbo"
DEFAULT_NUM_IMAGES = 2

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DTYPE = torch.float16 if DEVICE == "cuda" else torch.float32

print(f"Loading {MODEL_ID} on {DEVICE} ({DTYPE})")
pipe = AutoPipelineForText2Image.from_pretrained(
    MODEL_ID,
    torch_dtype=DTYPE,
    variant="fp16" if DEVICE == "cuda" else None,
    safety_checker=None,
)
pipe.to(DEVICE)
if DEVICE == "cuda":
    pipe.enable_attention_slicing()
print("Model ready")


def handler(job: dict[str, Any]) -> dict[str, Any]:
    """Generate N images and return public Cloudflare R2 URLs."""
    job_input = job.get("input") or {}
    prompt = job_input.get("prompt")
    num_images = job_input.get("num_images", DEFAULT_NUM_IMAGES)

    if not isinstance(prompt, str) or not prompt.strip():
        return {"error": "Missing required input field: prompt"}

    if not isinstance(num_images, int) or num_images < 1:
        return {"error": "num_images must be a positive integer"}

    images = []

    for _ in range(num_images):
        image = pipe(
            prompt=prompt.strip(),
            num_inference_steps=1,
            guidance_scale=0.0,
        ).images[0]

        url = upload_image(image)
        images.append(url)

    return {"images": images}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
