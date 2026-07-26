# Minimal Python 3.11 base for a portable Diffusers worker.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --requirement requirements.txt

COPY handler.py .

RUN useradd --create-home --uid 10001 worker \
    && mkdir -p /app/.cache/huggingface \
    && chown -R worker:worker /app
USER worker

CMD ["python", "-u", "handler.py"]
