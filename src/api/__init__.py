"""Arahus FastAPI package — production API + composition-root helpers.

Public helpers (backward compatible with the former ``src/api.py`` module)::

    from src.api import build_pipeline, generate_pipeline_result, create_app

Run the API::

    uvicorn src.api.app:app --reload --port 8000
"""

from __future__ import annotations

from src.api.app import app, create_app
from src.api.factory import (
    StubImageGenerator,
    StubStorageClient,
    build_pipeline,
    build_prompt_playground,
    generate_pipeline_result,
    generate_storyboard,
    playground_image_model,
)

__all__ = [
    "StubImageGenerator",
    "StubStorageClient",
    "app",
    "build_pipeline",
    "build_prompt_playground",
    "create_app",
    "generate_pipeline_result",
    "generate_storyboard",
    "playground_image_model",
]
