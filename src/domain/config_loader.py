"""Load and validate per-domain YAML prompt configurations."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

import yaml
from pydantic import ValidationError

from src.domain.models import DomainType
from src.domain.prompt_context import DomainPromptContext

logger = logging.getLogger(__name__)

DEFAULT_CONFIGS_DIR = Path(__file__).resolve().parent / "configs"

_REQUIRED_YAML_KEYS = frozenset(
    {
        "domain",
        "style",
        "camera",
        "lighting",
        "color_palette",
        "composition",
        "quality_tags",
        "negative_prompt",
        "image_model_defaults",
        "video_model_defaults",
    }
)


class ConfigLoaderError(Exception):
    """Raised when a domain YAML config cannot be loaded or validated."""

    def __init__(
        self,
        message: str,
        *,
        domain: DomainType | str | None = None,
        path: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.domain = domain
        self.path = path


class ConfigLoader:
    """YAML-backed loader for :class:`DomainPromptContext` values.

    Responsibilities:
        * Resolve ``{domain}.yaml`` under an injectable configs directory
        * Parse YAML and validate the required schema
        * Cache loaded contexts (disable via ``cache_enabled=False``)
        * Return immutable-style deep copies to callers

    Prompt style data lives only in YAML — not in Python source.
    """

    def __init__(
        self,
        configs_dir: Path | str | None = None,
        *,
        cache_enabled: bool = True,
    ) -> None:
        """Configure the loader.

        Args:
            configs_dir: Directory containing ``{domain}.yaml`` files.
                Defaults to :data:`DEFAULT_CONFIGS_DIR`.
            cache_enabled: When ``True``, memoize successful loads in memory.
        """
        self._configs_dir = Path(configs_dir) if configs_dir else DEFAULT_CONFIGS_DIR
        self._cache_enabled = cache_enabled
        self._cache: dict[DomainType, DomainPromptContext] = {}

    @property
    def configs_dir(self) -> Path:
        """Directory used to resolve domain YAML files."""
        return self._configs_dir

    @property
    def cache_enabled(self) -> bool:
        """Whether successful loads are cached."""
        return self._cache_enabled

    def load(self, domain: DomainType) -> DomainPromptContext:
        """Load and validate the YAML configuration for ``domain``.

        Args:
            domain: Target content domain.

        Returns:
            A validated :class:`DomainPromptContext` (deep copy if cached).

        Raises:
            ConfigLoaderError: If the file is missing, YAML is invalid, required
                fields are absent, or Pydantic validation fails.
            TypeError: If ``domain`` is not a :class:`DomainType`.
        """
        if not isinstance(domain, DomainType):
            raise TypeError("domain must be a DomainType")

        if self._cache_enabled and domain in self._cache:
            return self._cache[domain].model_copy(deep=True)

        path = self._path_for(domain)
        raw = self._read_yaml(path, domain=domain)
        context = self._validate_and_build(raw, domain=domain, path=path)

        if self._cache_enabled:
            self._cache[domain] = context

        logger.info(
            "event=domain_config_loaded domain=%s path=%s cached=%s",
            domain.value,
            path,
            self._cache_enabled,
        )
        return context.model_copy(deep=True)

    def clear_cache(self) -> None:
        """Drop all cached :class:`DomainPromptContext` entries."""
        self._cache.clear()

    def invalidate(self, domain: DomainType) -> None:
        """Remove a single domain from the cache if present."""
        self._cache.pop(domain, None)

    def cache_size(self) -> int:
        """Return the number of cached domain contexts."""
        return len(self._cache)

    def preload(self, domains: list[DomainType] | None = None) -> None:
        """Eagerly load ``domains`` (all :class:`DomainType` members by default)."""
        targets = list(DomainType) if domains is None else domains
        for domain in targets:
            self.load(domain)

    def _path_for(self, domain: DomainType) -> Path:
        return self._configs_dir / f"{domain.value}.yaml"

    def _read_yaml(self, path: Path, *, domain: DomainType) -> Mapping[str, Any]:
        if not path.is_file():
            raise ConfigLoaderError(
                f"Domain config file not found: {path}",
                domain=domain,
                path=path,
            )

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigLoaderError(
                f"Failed to read domain config {path}: {exc}",
                domain=domain,
                path=path,
            ) from exc

        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ConfigLoaderError(
                f"Invalid YAML in domain config {path}: {exc}",
                domain=domain,
                path=path,
            ) from exc

        if data is None:
            raise ConfigLoaderError(
                f"Domain config is empty: {path}",
                domain=domain,
                path=path,
            )
        if not isinstance(data, dict):
            raise ConfigLoaderError(
                f"Domain config root must be a mapping, got {type(data).__name__}: {path}",
                domain=domain,
                path=path,
            )
        return data

    def _validate_and_build(
        self,
        raw: Mapping[str, Any],
        *,
        domain: DomainType,
        path: Path,
    ) -> DomainPromptContext:
        missing = sorted(_REQUIRED_YAML_KEYS - set(raw.keys()))
        if missing:
            raise ConfigLoaderError(
                f"Domain config {path} missing required fields: {', '.join(missing)}",
                domain=domain,
                path=path,
            )

        file_domain = raw.get("domain")
        try:
            parsed_domain = DomainType(str(file_domain).strip().lower())
        except ValueError as exc:
            raise ConfigLoaderError(
                f"Domain config {path} has unknown domain value {file_domain!r}",
                domain=domain,
                path=path,
            ) from exc

        if parsed_domain != domain:
            raise ConfigLoaderError(
                f"Domain config {path} declares domain={parsed_domain.value!r} "
                f"but was loaded as {domain.value!r}",
                domain=domain,
                path=path,
            )

        image_defaults = raw.get("image_model_defaults")
        video_defaults = raw.get("video_model_defaults")
        if not isinstance(image_defaults, dict):
            raise ConfigLoaderError(
                f"Domain config {path} field 'image_model_defaults' must be a mapping",
                domain=domain,
                path=path,
            )
        if not isinstance(video_defaults, dict):
            raise ConfigLoaderError(
                f"Domain config {path} field 'video_model_defaults' must be a mapping",
                domain=domain,
                path=path,
            )

        payload = {
            "domain": parsed_domain,
            "style": raw.get("style"),
            "camera": raw.get("camera"),
            "lighting": raw.get("lighting"),
            "color_palette": raw.get("color_palette"),
            "composition": raw.get("composition"),
            "quality_tags": raw.get("quality_tags"),
            "negative_prompt": raw.get("negative_prompt"),
            "image_defaults": image_defaults,
            "video_defaults": video_defaults,
        }

        try:
            return DomainPromptContext.model_validate(payload)
        except ValidationError as exc:
            raise ConfigLoaderError(
                f"Domain config {path} failed schema validation: {exc}",
                domain=domain,
                path=path,
            ) from exc
