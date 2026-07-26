# A small, official Python 3.11 image keeps the worker portable and reduces
# image size and cold-start overhead.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies before copying application code to maximize layer reuse.
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --requirement requirements.txt

COPY handler.py .

# Run as an unprivileged user; the worker does not need root access.
RUN useradd --create-home --uid 10001 worker \
    && chown -R worker:worker /app
USER worker

CMD ["python", "-u", "handler.py"]
