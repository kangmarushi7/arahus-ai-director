# RunPod Serverless FLUX.1 [dev] Worker

Text-to-image worker using Hugging Face Diffusers and
`black-forest-labs/FLUX.1-dev`.

## Input

```json
{
  "input": {
    "prompt": "A futuristic cyberpunk city",
    "num_images": 1,
    "width": 1024,
    "height": 1024,
    "num_inference_steps": 28,
    "guidance_scale": 3.5
  }
}
```

`num_images` defaults to `1` when omitted. Size / steps / guidance fall back to
the FLUX.1-dev production defaults above when omitted.

## Output

```json
{
  "images": [
    "https://<r2-public-url>/..."
  ]
}
```

## Behavior

- Loads the model once at startup and reuses it for every job.
- Uses `torch.bfloat16` on CUDA when a GPU is available.
- Falls back to CPU (`float32`) when no GPU is present.
- Generates images with FLUX.1-dev defaults (`28` steps, `guidance_scale=3.5`,
  `1024×1024`).
- Uploads each PNG to Cloudflare R2 and returns public URLs.
- Accepts the Hugging Face license gate via `HF_TOKEN` /
  `HUGGINGFACE_HUB_TOKEN` (required to download `FLUX.1-dev`).
- Optional `FLUX_CPU_OFFLOAD=true` enables Diffusers model CPU offload on
  smaller GPUs.

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

### AI Director Studio (Streamlit — optional full UI)

```bash
streamlit run app/dashboard.py
```

### Arahus Lab (recommended E2E test UI)

FastAPI + clean browser UI for Railway / VPS. Enter a topic, stream live
progress, then inspect domain, research, scenes, review, images, and metrics.

```bash
# install web deps (no torch)
python -m pip install -r requirements.web.txt

# run locally
uvicorn src.webapp.main:app --reload --port 8000
# or
sh scripts/start_lab.sh
```

Open http://127.0.0.1:8000

#### Deploy on Railway

1. Create a Railway project from this repo.
2. Dockerfile is `Dockerfile.web` (see `railway.toml`).
3. The public site is **Arahus Studio** at `/`. Pipeline Lab is at `/lab`, admin logs at `/admin`.
4. Set environment variables:
   - **Required:** `OPENROUTER_API_KEY`
   - **Dry run (no images):** `ALLOW_STUB_SERVICES=true`
   - **Real images:** `RUNPOD_API_KEY`, `RUNPOD_ENDPOINT_ID`, and all `R2_*`
   - **Optional:** `DATABASE_URL`, `ARAHUS_API_KEY`
5. Railway sets `PORT` automatically.
6. Health check: `/health`

Local Docker:

```bash
docker build -f Dockerfile.web -t arahus-web .
docker run --rm -p 8000:8000 --env-file .ENV arahus-web
```

Studio talks to the API on the same origin via `/backend/*` (Caddy strips the prefix).
### Benchmark suite

```bash
python -m tests.benchmark
python -m reports.report_generator
```

Runs the full `DirectorPipeline` across 10 historical topics, writes
`artifacts/benchmark_results.json`, `artifacts/benchmark_results.csv`, and
`artifacts/report.html`, and prints a summary table (pipeline / research /
director / prompt / review / image timings, review score, image count).

## Build the container

```bash
docker build -t runpod-flux1-dev-worker .
```

Push the image to a registry and attach it to a RunPod Serverless endpoint.
On first start the worker downloads the model weights into `HF_HOME`. Set
`HF_TOKEN` in the endpoint secrets so the gated FLUX.1-dev weights can be
fetched. Prefer a GPU with **≥24 GB VRAM** (A10 / A100 / H100 class).

## Project layout

```
handler.py            RunPod worker entry point (global model load + job handler)
app/
└── dashboard.py      Streamlit AI Director Studio
src/
├── config.py         Nested Pydantic Settings (from env / .env)
├── agents/           research, director, prompt, review
├── services/         llm, runpod, r2, …
├── models/           Pydantic domain models
├── database/         base.py, session.py, models.py (SQLAlchemy ORM)
├── repositories/     project, scene, prompt data-access layer
├── playground/       prompt playground service
├── pipeline.py       DirectorPipeline orchestration
└── api.py            composition root
alembic/              PostgreSQL migrations
alembic.ini
requirements.txt
Dockerfile
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
ALLOW_STUB_SERVICES=false                          # optional; required for dry-runs without RunPod/R2
PROMPT_OPTIMIZER_ENABLED=true                      # optional
PIPELINE_MAX_COST_USD=0                            # optional; 0 = no cap
IMAGE_MAX_WORKERS=4                                # optional
LLM_CACHE_ENABLED=true                             # optional; caches domain detection
PERSIST_PIPELINE_RUNS=true                         # optional

# Image (RunPod / FLUX.1-dev)
RUNPOD_API_KEY=...
RUNPOD_ENDPOINT_ID=...
RUNPOD_BASE_URL=https://api.runpod.ai/v2           # optional
IMAGE_MODEL_ID=black-forest-labs/FLUX.1-dev        # optional label + worker override
IMAGE_WIDTH=1024                                   # optional
IMAGE_HEIGHT=1024                                  # optional
IMAGE_NUM_INFERENCE_STEPS=28                       # optional
IMAGE_GUIDANCE_SCALE=3.5                           # optional
HF_TOKEN=...                                       # required on the worker for gated FLUX weights

# Storage (R2)
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=...
R2_ENDPOINT=...
R2_PUBLIC_URL=...

# Database (PostgreSQL / Neon)
DATABASE_URL=postgresql://USER:PASSWORD@HOST/DB?sslmode=require

# Monitoring — see docs/observability.md
METRICS_ENABLED=true                               # optional
METRICS_INCLUDE_SAMPLES=false                      # optional
METRICS_EXPORT_PATH=                               # optional
```

LLM model precedence: explicit client model → non-empty `RESEARCH_MODEL` / `DIRECTOR_MODEL` / … → `src/llm/configs/router.yaml` task route. Copy `.env.example` for a full template.

See also [docs/observability.md](docs/observability.md). Video model defaults in domain YAML are reserved for a future video pipeline.
