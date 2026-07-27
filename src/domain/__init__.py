"""Domain Intelligence: multi-domain classification and configuration.

Independent of the director pipeline, database, RunPod, and agent modules.
Wire :class:`DomainService` into the pipeline later via dependency injection.
"""

from __future__ import annotations

from src.domain.config_loader import ConfigLoader, ConfigLoaderError
from src.domain.detector import (
    DomainDetector,
    DomainDetectorError,
    LLMDomainDetector,
)
from src.domain.models import (
    DomainConfig,
    DomainInfo,
    DomainResolution,
    DomainType,
)
from src.domain.prompt_context import DomainPromptContext
from src.domain.registry import (
    DomainRegistry,
    DomainRegistryError,
    default_domain_configs,
)
from src.domain.service import DomainService, DomainServiceError

__all__ = [
    "ConfigLoader",
    "ConfigLoaderError",
    "DomainConfig",
    "DomainDetector",
    "DomainDetectorError",
    "DomainInfo",
    "DomainPromptContext",
    "DomainRegistry",
    "DomainRegistryError",
    "DomainResolution",
    "DomainService",
    "DomainServiceError",
    "DomainType",
    "LLMDomainDetector",
    "default_domain_configs",
]
