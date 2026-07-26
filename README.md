# RunPod Serverless SDXL-Turbo Worker

Text-to-image worker using Hugging Face Diffusers and `stabilityai/sdxl-turbo`.

## Input

```json
{
  "input": {
    "prompt": "A futuristic cyberpunk city",
    "num_images": 2
  }
}
```

`num_images` defaults to `2` when omitted.

## Output

```json
{
  "images": [
    "<base64-encoded PNG>",
    "<base64-encoded PNG>"
  ]
}
```

## Behavior

- Loads the model once at startup and reuses it for every job.
- Uses `torch.float16` on CUDA when a GPU is available.
- Falls back to CPU (`float32`) when no GPU is present.
- Generates images sequentially with SDXL-Turbo defaults (`1` step, `guidance_scale=0.0`).

## Local setup

```bash
python -m venv .venv
```

Activate, then install:

```bash
# Linux or macOS
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt
```

## Build the container

```bash
docker build -t runpod-sdxl-turbo-worker .
```

Push the image to a registry and attach it to a RunPod Serverless endpoint.
On first start the worker downloads the model weights into `HF_HOME`.

## Project files

- `handler.py` — global model load + job handler
- `requirements.txt` — Diffusers / Torch stack
- `Dockerfile` — minimal Python 3.11 image
