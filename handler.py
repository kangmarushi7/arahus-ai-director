"""RunPod Serverless worker for SDXL-Turbo text-to-image generation."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import runpod
import torch
from diffusers import AutoPipelineForText2Image

# Model is loaded once at cold start and reused across jobs.
MODEL_ID = "stabilityai/sdxl-turbo"
OUTPUT_PATH = Path("output.png")

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


def handler(job: dict[str, Any]) -> dict[str, str]:
    """Generate one image from a text prompt and return it as base64 PNG."""
    job_input = job.get("input") or {}
    prompt = job_input.get("prompt")

    if not isinstance(prompt, str) or not prompt.strip():
        return {"error": "Missing required input field: prompt"}

    # SDXL-Turbo is designed for 1-step inference with guidance disabled.
    image = pipe(
        prompt=prompt.strip(),
        num_inference_steps=1,
        guidance_scale=0.0,
    ).images[0]

    image.save(OUTPUT_PATH)
    image_b64 = base64.b64encode(OUTPUT_PATH.read_bytes()).decode("utf-8")

    return {"image": image_b64}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
