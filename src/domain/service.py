"""Facade service for domain detection and configuration lookup."""

from __future__ import annotations

import logging

from src.domain.config_loader import ConfigLoader, ConfigLoaderError
from src.domain.detector import DomainDetector, DomainDetectorError
from src.domain.models import (
    DomainConfig,
    DomainInfo,
    DomainResolution,
    DomainType,
)
from src.domain.prompt_context import DomainPromptContext
from src.domain.registry import DomainRegistry, DomainRegistryError

logger = logging.getLogger(__name__)


class DomainServiceError(Exception):
    """Raised when :class:`DomainService` cannot complete an operation."""

    def __init__(self, message: str, *, topic: str | None = None) -> None:
        super().__init__(message)
        self.topic = topic


class DomainService:
    """Single API for domain intelligence used by the pipeline.

    Combines an injected :class:`~src.domain.detector.DomainDetector` with a
    :class:`~src.domain.registry.DomainRegistry` and YAML
    :class:`~src.domain.config_loader.ConfigLoader`. This module stays
    independent of agents, database, and image infrastructure.
    """

    def __init__(
        self,
        detector: DomainDetector,
        registry: DomainRegistry | None = None,
        config_loader: ConfigLoader | None = None,
        *,
        enrich_from_registry: bool = True,
    ) -> None:
        """Wire detector, registry, and YAML config loader collaborators.

        Args:
            detector: Topic → :class:`DomainInfo` classifier.
            registry: Domain configuration store. Defaults to a registry with
                built-in configs when omitted.
            config_loader: YAML prompt-context loader. Defaults to
                :class:`ConfigLoader` pointing at packaged configs.
            enrich_from_registry: When ``True``, empty suggestion fields on
                :class:`DomainInfo` are filled from the matching registry config.
        """
        if detector is None:
            raise ValueError("detector is required")
        self._detector = detector
        self._registry = registry if registry is not None else DomainRegistry()
        self._config_loader = (
            config_loader if config_loader is not None else ConfigLoader()
        )
        self._enrich_from_registry = enrich_from_registry

    @property
    def registry(self) -> DomainRegistry:
        """Expose the bound registry for plugins and diagnostics."""
        return self._registry

    @property
    def config_loader(self) -> ConfigLoader:
        """Expose the bound YAML config loader."""
        return self._config_loader

    def detect(self, topic: str) -> DomainInfo:
        """Detect the domain for ``topic``.

        Args:
            topic: Free-form subject or brief.

        Returns:
            :class:`DomainInfo`, optionally enriched from the registry.

        Raises:
            ValueError: If ``topic`` is empty.
            DomainServiceError: If detection fails.
        """
        try:
            info = self._detector.detect(topic)
        except ValueError:
            raise
        except DomainDetectorError as exc:
            raise DomainServiceError(str(exc), topic=exc.topic) from exc

        if self._enrich_from_registry:
            info = self._enrich(info)

        logger.info(
            "event=domain_service_detect topic=%r domain=%s confidence=%.3f",
            topic,
            info.domain.value,
            info.confidence,
        )
        return info

    def get_configuration(self, domain: DomainType) -> DomainConfig:
        """Return the registered configuration for ``domain``.

        Raises:
            DomainServiceError: If the domain is not registered.
        """
        try:
            return self._registry.get(domain)
        except DomainRegistryError as exc:
            raise DomainServiceError(str(exc)) from exc

    def get_prompt_context(self, domain: DomainType) -> DomainPromptContext:
        """Return YAML-backed prompt context for ``domain``.

        Args:
            domain: Detected or requested content domain.

        Returns:
            Validated :class:`DomainPromptContext` for Prompt Agent injection.

        Raises:
            DomainServiceError: If the YAML config is missing or invalid.
        """
        try:
            context = self._config_loader.load(domain)
        except ConfigLoaderError as exc:
            raise DomainServiceError(str(exc)) from exc

        logger.info(
            "event=domain_prompt_context domain=%s style_chars=%s",
            context.domain.value,
            len(context.style),
        )
        return context

    def resolve(self, topic: str) -> DomainResolution:
        """Detect domain and return detection + configuration for the pipeline.

        This is the preferred single entry point for future pipeline wiring.

        Args:
            topic: Free-form subject or brief.

        Returns:
            :class:`DomainResolution` with ``info`` and ``config``.

        Raises:
            ValueError: If ``topic`` is empty.
            DomainServiceError: If detection or config lookup fails.
        """
        info = self.detect(topic)
        config = self.get_configuration(info.domain)
        return DomainResolution(info=info, config=config)

    def list_domains(self) -> list[DomainType]:
        """Return domains currently available in the registry."""
        return self._registry.list_domains()

    def _enrich(self, info: DomainInfo) -> DomainInfo:
        """Fill blank suggestion fields from registry / YAML when available."""
        updates: dict[str, object] = {}

        if self._registry.has(info.domain):
            config = self._registry.get(info.domain)
            if not info.suggested_style.strip():
                updates["suggested_style"] = config.suggested_style
            if not info.suggested_camera.strip():
                updates["suggested_camera"] = config.suggested_camera
            if not info.suggested_negative_prompt.strip():
                updates["suggested_negative_prompt"] = config.suggested_negative_prompt
            if not info.keywords and config.default_keywords:
                updates["keywords"] = list(config.default_keywords)

        # Prefer YAML prompt context when registry suggestions are still blank.
        try:
            prompt_ctx = self._config_loader.load(info.domain)
        except ConfigLoaderError:
            prompt_ctx = None

        if prompt_ctx is not None:
            if not str(updates.get("suggested_style") or info.suggested_style).strip():
                updates["suggested_style"] = prompt_ctx.style
            if not str(updates.get("suggested_camera") or info.suggested_camera).strip():
                updates["suggested_camera"] = prompt_ctx.camera
            if not str(
                updates.get("suggested_negative_prompt") or info.suggested_negative_prompt
            ).strip():
                updates["suggested_negative_prompt"] = prompt_ctx.negative_prompt

        if not updates:
            return info
        return info.model_copy(update=updates)
