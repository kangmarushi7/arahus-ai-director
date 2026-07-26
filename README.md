# Minimal RunPod Serverless Worker

A production-ready Python 3.11 worker that returns:

```json
{"message": "Hello World"}
```

## Local setup

```bash
python -m venv .venv
```

Activate the virtual environment:

```bash
# Linux or macOS
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install the pinned RunPod SDK and verify the handler:

```bash
python -m pip install -r requirements.txt
python -c "from handler import handler; print(handler({}))"
```

## Build the container

```bash
docker build -t runpod-hello-worker .
```

Push the image to a container registry, then configure a RunPod Serverless
endpoint to use that image. No HTTP framework or exposed port is needed:
the RunPod SDK starts the worker and receives jobs from the platform.

## Project files

- `handler.py` defines the job handler and starts the RunPod event loop.
- `requirements.txt` pins the SDK for reproducible builds.
- `Dockerfile` creates a small image and runs as a non-root user.
