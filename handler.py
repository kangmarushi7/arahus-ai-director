"""RunPod Serverless worker for SDXL-Turbo text-to-image generation."""

from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

import runpod
import torch
from diffusers import AutoPipelineForText2Image
from PIL import Image

# Model is loaded once at cold start and reused across jobs.
MODEL_ID = "stabilityai/sdxl-turbo"
DEFAULT_NUM_IMAGES = 4

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


def image_to_base64(image: Image.Image) -> str:
    """Encode a PIL image as a base64 PNG string."""
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def handler(job: dict[str, Any]) -> dict[str, Any]:
    """Generate N images from a text prompt and return them as base64 PNGs."""
    job_input = job.get("input") or {}
    prompt = job_input.get("prompt")
    num_images = job_input.get("num_images", DEFAULT_NUM_IMAGES)

    if not isinstance(prompt, str) or not prompt.strip():
        return {"error": "Missing required input field: prompt"}

    if not isinstance(num_images, int) or num_images < 1:
        return {"error": "num_images must be a positive integer"}

    # One pipeline call generates all images; SDXL-Turbo uses 1 step + no guidance.
    result = pipe(
        prompt=prompt.strip(),
        num_inference_steps=1,
        guidance_scale=0.0,
        num_images_per_prompt=num_images,
    )

    return {"images": [image_to_base64(image) for image in result.images]}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
