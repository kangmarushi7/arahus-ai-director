"""Domain configuration registry with built-in defaults and plugin hooks."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping

from src.domain.models import DomainConfig, DomainType

logger = logging.getLogger(__name__)


def default_domain_configs() -> dict[DomainType, DomainConfig]:
    """Return the built-in configuration map for every :class:`DomainType`."""
    configs: list[DomainConfig] = [
        DomainConfig(
            domain=DomainType.HISTORY,
            label="History",
            description=(
                "Period-accurate historical events, figures, and material culture."
            ),
            default_keywords=[
                "historical",
                "period-accurate",
                "documentary",
                "archival",
            ],
            suggested_style=(
                "cinematic historical drama, period-accurate costumes and "
                "architecture, natural lighting, muted earth tones, film grain"
            ),
            suggested_camera=(
                "35mm anamorphic, medium-wide establishing shots, slow push-ins, "
                "eye-level documentary framing"
            ),
            suggested_negative_prompt=(
                "modern clothing, smartphones, neon lights, sci-fi elements, "
                "anachronisms, cartoon, anime, low detail"
            ),
        ),
        DomainConfig(
            domain=DomainType.SCIFI,
            label="Sci-Fi",
            description="Speculative science fiction worlds, tech, and futures.",
            default_keywords=[
                "science fiction",
                "futuristic",
                "technology",
                "spacecraft",
            ],
            suggested_style=(
                "high-concept science fiction, sleek industrial design, "
                "volumetric light, cool metallic palette, cinematic VFX"
            ),
            suggested_camera=(
                "wide anamorphic sci-fi framing, low-angle hero shots, "
                "tracking through corridors, shallow depth of field"
            ),
            suggested_negative_prompt=(
                "medieval, historical costumes, fantasy magic, rustic, "
                "cartoon, low-poly, blurry"
            ),
        ),
        DomainConfig(
            domain=DomainType.FINANCE,
            label="Finance",
            description="Markets, banking, investing, and economic narratives.",
            default_keywords=[
                "finance",
                "markets",
                "trading",
                "economy",
            ],
            suggested_style=(
                "clean corporate editorial, glass and steel interiors, "
                "crisp daylight, high contrast charts aesthetic, premium polish"
            ),
            suggested_camera=(
                "50mm corporate documentary, over-shoulder terminal views, "
                "static tripod interviews, subtle gimbal moves"
            ),
            suggested_negative_prompt=(
                "fantasy, spaceships, medieval, horror, grunge, cartoon, "
                "cluttered backgrounds"
            ),
        ),
        DomainConfig(
            domain=DomainType.EDUCATION,
            label="Education",
            description="Instructional and explanatory learning content.",
            default_keywords=[
                "education",
                "learning",
                "explainer",
                "classroom",
            ],
            suggested_style=(
                "clear instructional visual language, bright even lighting, "
                "approachable realism, high readability, friendly color accents"
            ),
            suggested_camera=(
                "eye-level 35mm, simple compositions, medium shots of subjects "
                "and materials, minimal camera motion"
            ),
            suggested_negative_prompt=(
                "horror, gore, darkness, chaotic framing, heavy grain, "
                "distracting clutter, low contrast"
            ),
        ),
        DomainConfig(
            domain=DomainType.MARKETING,
            label="Marketing",
            description="Brand, product, and campaign-oriented storytelling.",
            default_keywords=[
                "marketing",
                "brand",
                "campaign",
                "product",
            ],
            suggested_style=(
                "polished commercial advertising, lifestyle photography look, "
                "vibrant controlled color grade, aspirational lighting"
            ),
            suggested_camera=(
                "85mm product beauty, hero angles, smooth slider moves, "
                "shallow depth of field"
            ),
            suggested_negative_prompt=(
                "dirty, dystopian, horror, low quality, watermark, text overlays, "
                "distorted hands, cluttered frame"
            ),
        ),
        DomainConfig(
            domain=DomainType.FANTASY,
            label="Fantasy",
            description="Mythic, magical, and secondary-world fantasy.",
            default_keywords=[
                "fantasy",
                "magic",
                "mythic",
                "epic",
            ],
            suggested_style=(
                "epic fantasy illustration-cinema hybrid, rich saturated colors, "
                "dramatic god-rays, ornate costumes and architecture"
            ),
            suggested_camera=(
                "wide epic establishing shots, crane reveals, low-angle heroes, "
                "slow orbital moves"
            ),
            suggested_negative_prompt=(
                "modern city, smartphones, sci-fi HUD, corporate office, "
                "photorealistic guns, cartoonish proportions"
            ),
        ),
        DomainConfig(
            domain=DomainType.TECHNOLOGY,
            label="Technology",
            description="Products, engineering, software, and innovation.",
            default_keywords=[
                "technology",
                "innovation",
                "engineering",
                "software",
            ],
            suggested_style=(
                "modern tech keynote aesthetic, clean minimalism, soft studio "
                "lighting, precise materials, cool-neutral palette"
            ),
            suggested_camera=(
                "macro and mid product shots, controlled dolly, top-down desks, "
                "sharp focus on devices and interfaces"
            ),
            suggested_negative_prompt=(
                "fantasy castles, medieval armor, messy cables overload, "
                "dated CRT look unless intentional, cartoon"
            ),
        ),
        DomainConfig(
            domain=DomainType.BUSINESS,
            label="Business",
            description="Organizations, strategy, leadership, and operations.",
            default_keywords=[
                "business",
                "corporate",
                "leadership",
                "strategy",
            ],
            suggested_style=(
                "professional corporate photography, natural office light, "
                "neutral wardrobe, calm confident tone"
            ),
            suggested_camera=(
                "35–50mm meeting coverage, over-shoulder boardroom, "
                "stable handheld or tripod"
            ),
            suggested_negative_prompt=(
                "sci-fi, fantasy, horror, extreme angles, neon cyberpunk, "
                "cartoon, exaggerated expressions"
            ),
        ),
        DomainConfig(
            domain=DomainType.GENERAL,
            label="General",
            description="Fallback domain when no specialist category fits.",
            default_keywords=["general", "narrative", "cinematic"],
            suggested_style=(
                "cinematic realism, balanced natural color, soft contrast, "
                "versatile contemporary look"
            ),
            suggested_camera=(
                "35mm cinematic, eye-level framing, gentle motivated camera moves"
            ),
            suggested_negative_prompt=(
                "low quality, blurry, watermark, deformed, extra limbs, text"
            ),
        ),
    ]
    return {config.domain: config for config in configs}


class DomainRegistryError(Exception):
    """Raised for invalid registry operations."""


class DomainRegistry:
    """In-memory registry of :class:`DomainConfig` entries.

    Supports replacing or extending built-in domains so future plugins can
    register configurations without changing detector or service code.
    """

    def __init__(
        self,
        configs: Mapping[DomainType, DomainConfig] | None = None,
        *,
        include_defaults: bool = True,
    ) -> None:
        """Initialize the registry.

        Args:
            configs: Optional initial map of domain → config. When
                ``include_defaults`` is ``True``, defaults are loaded first and
                ``configs`` overlays them.
            include_defaults: Load :func:`default_domain_configs` when ``True``.
        """
        self._configs: dict[DomainType, DomainConfig] = {}
        if include_defaults:
            self._configs.update(default_domain_configs())
        if configs:
            for domain, config in configs.items():
                self.register(config, replace=True)
                if config.domain != domain:
                    raise DomainRegistryError(
                        f"Config domain {config.domain!r} does not match "
                        f"map key {domain!r}"
                    )

    def register(
        self,
        config: DomainConfig,
        *,
        replace: bool = False,
    ) -> None:
        """Register or replace a domain configuration.

        Args:
            config: Configuration to store.
            replace: When ``False``, raises if the domain is already registered.

        Raises:
            DomainRegistryError: If the domain exists and ``replace`` is false.
            TypeError: If ``config`` is not a :class:`DomainConfig`.
        """
        if not isinstance(config, DomainConfig):
            raise TypeError("config must be a DomainConfig instance")
        if config.domain in self._configs and not replace:
            raise DomainRegistryError(
                f"Domain {config.domain.value!r} is already registered; "
                "pass replace=True to overwrite"
            )
        self._configs[config.domain] = config
        logger.info(
            "event=domain_registered domain=%s replace=%s",
            config.domain.value,
            replace,
        )

    def unregister(self, domain: DomainType) -> None:
        """Remove a domain configuration if present.

        Raises:
            DomainRegistryError: If ``domain`` is not registered.
        """
        if domain not in self._configs:
            raise DomainRegistryError(
                f"Domain {domain.value!r} is not registered"
            )
        del self._configs[domain]
        logger.info("event=domain_unregistered domain=%s", domain.value)

    def get(self, domain: DomainType) -> DomainConfig:
        """Return a deep copy of the configuration for ``domain``.

        Raises:
            DomainRegistryError: If ``domain`` is not registered.
        """
        try:
            config = self._configs[domain]
        except KeyError as exc:
            raise DomainRegistryError(
                f"No configuration registered for domain {domain.value!r}"
            ) from exc
        return config.model_copy(deep=True)

    def has(self, domain: DomainType) -> bool:
        """Return whether ``domain`` has a registered configuration."""
        return domain in self._configs

    def list_domains(self) -> list[DomainType]:
        """Return registered domains in enum definition order when possible."""
        known = [member for member in DomainType if member in self._configs]
        extras = [
            domain
            for domain in self._configs
            if domain not in known
        ]
        return known + extras

    def all_configs(self) -> list[DomainConfig]:
        """Return deep copies of every registered configuration."""
        return [self.get(domain) for domain in self.list_domains()]

    def extend(self, configs: Iterable[DomainConfig], *, replace: bool = False) -> None:
        """Register many configurations (plugin batch hook)."""
        for config in configs:
            self.register(config, replace=replace)
