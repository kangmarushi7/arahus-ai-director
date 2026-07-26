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

## Project layout

```
handler.py            RunPod worker entry point (global model load + job handler)
src/
├── config.py         OpenRouter models and sampling (from env)
├── agents/           research.py, director.py, prompt.py
├── services/         llm.py, llm_factory.py, runpod.py, r2.py
├── models/           research.py, storyboard.py, image.py
├── pipeline.py       DirectorPipeline orchestration
└── api.py            composition root
requirements.txt      Diffusers / Torch stack
Dockerfile            minimal Python 3.11 image
```

## Pipeline

`DirectorPipeline.generate(topic)` runs the workflow end to end:

1. `ResearchAgent` → `ResearchResult`
2. `DirectorAgent` → `DirectorPlan`
3. `PromptAgent` → `Storyboard`
4. `ReviewAgent` → `ReviewResult`
5. Regenerate rejected storyboards up to three times
6. Generate an image per approved scene, upload it, and attach the URL

Each agent receives its own `LLMClient` from `create_llm(...)`, using the
models in `settings.llm`. Agents never see OpenRouter details.

Configuration is nested and loaded by Pydantic Settings from process env
(RunPod Secrets) and an optional `.env` file:

- `settings.llm` — OpenRouter key/URL, models, temperature, max tokens
- `settings.image` — RunPod key/endpoint
- `settings.storage` — Cloudflare R2
- `settings.pipeline` — retries, approval threshold, agent debug
- `settings.monitoring` — metrics toggles

### Pipeline environment variables

```bash
# LLM (OpenRouter)
OPENROUTER_API_KEY=...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1   # optional
RESEARCH_MODEL=openai/gpt-oss-20b:free             # optional
DIRECTOR_MODEL=nvidia/llama-3.1-nemotron-ultra-253b-v1:free  # optional
PROMPT_MODEL=openai/gpt-oss-20b:free               # optional
REVIEW_MODEL=openai/gpt-oss-20b:free               # optional; defaults to PROMPT_MODEL
LLM_TEMPERATURE=0.2                                # optional
LLM_MAX_TOKENS=4000                                # optional

# Pipeline
MAX_STORYBOARD_RETRIES=3                           # optional
REVIEW_APPROVAL_THRESHOLD=85                       # optional
AGENT_DEBUG=false                                  # optional

# Image (RunPod)
RUNPOD_API_KEY=...
RUNPOD_ENDPOINT_ID=...
RUNPOD_BASE_URL=https://api.runpod.ai/v2           # optional

# Storage (R2)
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=...
R2_ENDPOINT=...
R2_PUBLIC_URL=...

# Monitoring
METRICS_ENABLED=true                               # optional
METRICS_INCLUDE_SAMPLES=false                      # optional
METRICS_EXPORT_PATH=                               # optional
```
