"""Nested runtime configuration loaded from environment variables.

Supports ``.env`` files and process environment (including RunPod Secrets).
Secrets are never hardcoded — only empty defaults or non-secret public URLs
and model ids are defined here.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = (".env", ".ENV")


class _SectionSettings(BaseSettings):
    """Shared settings behaviour for every nested config section."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )


class LLMConfig(_SectionSettings):
    """OpenRouter / OpenAI-compatible LLM settings."""

    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="OPENROUTER_API_KEY")
    base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        validation_alias="OPENROUTER_BASE_URL",
    )
    research_model: str = Field(default="", validation_alias="RESEARCH_MODEL")
    director_model: str = Field(default="", validation_alias="DIRECTOR_MODEL")
    prompt_model: str = Field(default="", validation_alias="PROMPT_MODEL")
    review_model: str = Field(default="", validation_alias="REVIEW_MODEL")
    domain_model: str = Field(default="", validation_alias="DOMAIN_MODEL")
    temperature: float = Field(default=0.2, validation_alias="LLM_TEMPERATURE")
    max_tokens: int = Field(default=4000, ge=1, validation_alias="LLM_MAX_TOKENS")

    @field_validator("base_url")
    @classmethod
    def _require_base_url(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must be a non-empty string")
        return cleaned.rstrip("/")

    @field_validator(
        "research_model",
        "director_model",
        "prompt_model",
        "review_model",
        "domain_model",
    )
    @classmethod
    def _strip_optional_model(cls, value: str) -> str:
        """Allow empty env overrides so router.yaml defaults apply."""
        return value.strip()

    def model_override_for(self, task: str) -> str | None:
        """Return a non-empty env model override for ``task``, if configured.

        Precedence (enforced by the factory + router):
        1. Explicit ``LLMClient.model`` / ``generate(..., model=)``
        2. Non-empty env override for this task (this method)
        3. ``router.yaml`` task route model
        """
        key = task.strip().lower()
        mapping = {
            "research": self.research_model,
            "director": self.director_model,
            "prompt": self.prompt_model,
            "review": self.review_model,
            "domain": self.domain_model,
            "general": self.prompt_model,
        }
        value = (mapping.get(key) or "").strip()
        return value or None

    def require_api_key(self) -> str:
        """Return the API key or raise when it is missing."""
        key = self.api_key.get_secret_value().strip()
        if not key:
            raise RuntimeError(
                "Missing required environment variable: OPENROUTER_API_KEY"
            )
        return key


class ImageConfig(_SectionSettings):
    """RunPod image-generation settings."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
        protected_namespaces=("settings_",),
    )

    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="RUNPOD_API_KEY")
    endpoint_id: str = Field(default="", validation_alias="RUNPOD_ENDPOINT_ID")
    base_url: str = Field(
        default="https://api.runpod.ai/v2",
        validation_alias="RUNPOD_BASE_URL",
    )
    model_id: str = Field(
        default="black-forest-labs/FLUX.1-dev",
        validation_alias="IMAGE_MODEL_ID",
    )
    width: int = Field(default=1024, validation_alias="IMAGE_WIDTH")
    height: int = Field(default=1024, validation_alias="IMAGE_HEIGHT")
    num_inference_steps: int = Field(
        default=28,
        validation_alias="IMAGE_NUM_INFERENCE_STEPS",
    )
    guidance_scale: float = Field(
        default=3.5,
        validation_alias="IMAGE_GUIDANCE_SCALE",
    )

    def require_credentials(self) -> tuple[str, str]:
        """Return ``(api_key, endpoint_id)`` or raise when either is missing."""
        key = self.api_key.get_secret_value().strip()
        endpoint = self.endpoint_id.strip()
        if not key:
            raise RuntimeError("Missing required environment variable: RUNPOD_API_KEY")
        if not endpoint:
            raise RuntimeError(
                "Missing required environment variable: RUNPOD_ENDPOINT_ID"
            )
        return key, endpoint

    def generation_input(self, prompt: str, *, num_images: int = 1) -> dict[str, object]:
        """Build the RunPod ``input`` object for a FLUX.1-dev job."""
        return {
            "prompt": prompt,
            "num_images": num_images,
            "width": self.width,
            "height": self.height,
            "num_inference_steps": self.num_inference_steps,
            "guidance_scale": self.guidance_scale,
        }


class StorageConfig(_SectionSettings):
    """Cloudflare R2 object-storage settings."""

    access_key_id: SecretStr = Field(
        default=SecretStr(""),
        validation_alias="R2_ACCESS_KEY_ID",
    )
    secret_access_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias="R2_SECRET_ACCESS_KEY",
    )
    bucket: str = Field(default="", validation_alias="R2_BUCKET")
    endpoint: str = Field(default="", validation_alias="R2_ENDPOINT")
    public_url: str = Field(default="", validation_alias="R2_PUBLIC_URL")

    def require_complete(self) -> StorageConfig:
        """Validate that every R2 setting required for uploads is present."""
        missing: list[str] = []
        if not self.access_key_id.get_secret_value().strip():
            missing.append("R2_ACCESS_KEY_ID")
        if not self.secret_access_key.get_secret_value().strip():
            missing.append("R2_SECRET_ACCESS_KEY")
        if not self.bucket.strip():
            missing.append("R2_BUCKET")
        if not self.endpoint.strip():
            missing.append("R2_ENDPOINT")
        if not self.public_url.strip():
            missing.append("R2_PUBLIC_URL")
        if missing:
            raise RuntimeError(
                "Missing required environment variable(s): " + ", ".join(missing)
            )
        return self


class PipelineConfig(_SectionSettings):
    """Orchestration behaviour for :class:`~src.pipeline.DirectorPipeline`."""

    max_storyboard_retries: int = Field(
        default=3,
        ge=0,
        validation_alias="MAX_STORYBOARD_RETRIES",
    )
    approval_threshold: float = Field(
        default=85.0,
        ge=0,
        le=100,
        validation_alias="REVIEW_APPROVAL_THRESHOLD",
    )
    agent_debug: bool = Field(default=False, validation_alias="AGENT_DEBUG")
    prompt_optimizer_enabled: bool = Field(
        default=True,
        validation_alias="PROMPT_OPTIMIZER_ENABLED",
    )
    max_cost_usd: float = Field(
        default=0.0,
        ge=0.0,
        validation_alias="PIPELINE_MAX_COST_USD",
    )
    image_max_workers: int = Field(
        default=4,
        ge=1,
        validation_alias=AliasChoices("MAX_PARALLEL_IMAGES", "IMAGE_MAX_WORKERS"),
    )
    allow_stub_services: bool = Field(
        default=False,
        validation_alias="ALLOW_STUB_SERVICES",
    )
    llm_cache_enabled: bool = Field(
        default=True,
        validation_alias="LLM_CACHE_ENABLED",
    )
    persist_pipeline_runs: bool = Field(
        default=True,
        validation_alias="PERSIST_PIPELINE_RUNS",
    )


class MonitoringConfig(_SectionSettings):
    """In-memory metrics collection settings."""

    enabled: bool = Field(default=True, validation_alias="METRICS_ENABLED")
    include_samples: bool = Field(
        default=False,
        validation_alias="METRICS_INCLUDE_SAMPLES",
    )
    export_path: str = Field(default="", validation_alias="METRICS_EXPORT_PATH")
    json_logging: bool = Field(
        default=False,
        validation_alias="METRICS_JSON_LOGGING",
    )


class DatabaseConfig(_SectionSettings):
    """PostgreSQL connection settings (Neon and other providers)."""

    url: SecretStr = Field(default=SecretStr(""), validation_alias="DATABASE_URL")

    def require_url(self) -> str:
        """Return ``DATABASE_URL`` or raise when it is missing."""
        value = self.url.get_secret_value().strip()
        if not value:
            raise RuntimeError("Missing required environment variable: DATABASE_URL")
        return value


class AppConfig(BaseSettings):
    """Root application configuration composed of nested sections.

    Environment sources, in order of precedence:
    1. Process environment (RunPod Secrets, shell exports, CI secrets)
    2. Optional ``.env`` file in the working directory
    3. Declared defaults for non-secret values
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
    )

    llm: LLMConfig = Field(default_factory=LLMConfig)
    image: ImageConfig = Field(default_factory=ImageConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)


@lru_cache(maxsize=1)
def get_settings() -> AppConfig:
    """Load and cache the application configuration.

    Nested sections each read from the process environment and ``.env``, so
    RunPod Secrets injected as env vars are picked up automatically.
    """
    return AppConfig(
        llm=LLMConfig(),
        image=ImageConfig(),
        storage=StorageConfig(),
        pipeline=PipelineConfig(),
        monitoring=MonitoringConfig(),
        database=DatabaseConfig(),
    )


def reload_settings() -> AppConfig:
    """Clear the settings cache and reload from the current environment."""
    get_settings.cache_clear()
    return get_settings()
