"""Unit tests for YAML domain ConfigLoader."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.domain.config_loader import ConfigLoader, ConfigLoaderError
from src.domain.detector import DomainDetector
from src.domain.models import DomainInfo, DomainType
from src.domain.prompt_context import DomainPromptContext
from src.domain.service import DomainService

_MINIMAL_YAML = """\
domain: {domain}
style: test style
camera: test camera
lighting: test lighting
color_palette: test palette
composition: test composition
quality_tags:
  - tag-a
  - tag-b
negative_prompt: bad things
image_model_defaults:
  width: 512
  height: 512
video_model_defaults:
  fps: 24
"""


class _FixedDetector(DomainDetector):
    def __init__(self, domain: DomainType) -> None:
        self._domain = domain

    def detect(self, topic: str) -> DomainInfo:
        return DomainInfo(
            domain=self._domain,
            confidence=1.0,
            reasoning="fixed",
            keywords=[],
        )


def _write_domain_yaml(directory: Path, domain: DomainType, body: str) -> Path:
    path = directory / f"{domain.value}.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _drop_key_block(yaml_text: str, key: str) -> str:
    """Remove ``key:`` and any following indented block from YAML text."""
    lines = yaml_text.splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        if line.startswith(f"{key}:"):
            skipping = True
            continue
        if skipping:
            if line.startswith(" ") or line.strip() == "":
                continue
            skipping = False
        out.append(line)
    return "\n".join(out) + "\n"


class TestConfigLoaderLoad:
    def test_loads_packaged_history_config(self) -> None:
        loader = ConfigLoader(cache_enabled=False)
        context = loader.load(DomainType.HISTORY)

        assert isinstance(context, DomainPromptContext)
        assert context.domain == DomainType.HISTORY
        assert context.style
        assert context.camera
        assert context.lighting
        assert context.composition
        assert context.color_palette
        assert context.negative_prompt
        assert isinstance(context.quality_tags, list)
        assert context.quality_tags
        assert isinstance(context.image_defaults, dict)
        assert isinstance(context.video_defaults, dict)
        assert context.image_defaults.get("width") == 1024

    def test_loads_all_packaged_domains(self) -> None:
        loader = ConfigLoader(cache_enabled=False)
        for domain in DomainType:
            context = loader.load(domain)
            assert context.domain == domain
            assert context.style.strip()
            assert context.negative_prompt.strip()


class TestConfigLoaderInvalidYaml:
    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        _write_domain_yaml(
            tmp_path,
            DomainType.GENERAL,
            "domain: general\nstyle: [unclosed",
        )
        loader = ConfigLoader(configs_dir=tmp_path, cache_enabled=False)

        with pytest.raises(ConfigLoaderError, match="Invalid YAML"):
            loader.load(DomainType.GENERAL)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        loader = ConfigLoader(configs_dir=tmp_path, cache_enabled=False)

        with pytest.raises(ConfigLoaderError, match="not found"):
            loader.load(DomainType.HISTORY)

    def test_domain_mismatch_raises(self, tmp_path: Path) -> None:
        _write_domain_yaml(
            tmp_path,
            DomainType.HISTORY,
            _MINIMAL_YAML.format(domain="scifi"),
        )
        loader = ConfigLoader(configs_dir=tmp_path, cache_enabled=False)

        with pytest.raises(ConfigLoaderError, match="declares domain"):
            loader.load(DomainType.HISTORY)


class TestConfigLoaderMissingFields:
    @pytest.mark.parametrize(
        "missing_key",
        [
            "style",
            "camera",
            "lighting",
            "color_palette",
            "composition",
            "quality_tags",
            "negative_prompt",
            "image_model_defaults",
            "video_model_defaults",
        ],
    )
    def test_missing_required_field_raises(
        self,
        tmp_path: Path,
        missing_key: str,
    ) -> None:
        body = _drop_key_block(_MINIMAL_YAML.format(domain="general"), missing_key)
        _write_domain_yaml(tmp_path, DomainType.GENERAL, body)
        loader = ConfigLoader(configs_dir=tmp_path, cache_enabled=False)

        with pytest.raises(ConfigLoaderError, match="missing required fields"):
            loader.load(DomainType.GENERAL)

    def test_empty_file_raises(self, tmp_path: Path) -> None:
        _write_domain_yaml(tmp_path, DomainType.GENERAL, "")
        loader = ConfigLoader(configs_dir=tmp_path, cache_enabled=False)

        with pytest.raises(ConfigLoaderError, match="empty"):
            loader.load(DomainType.GENERAL)


class TestConfigLoaderCache:
    def test_cache_returns_cached_copy_and_skips_reread(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = _write_domain_yaml(
            tmp_path,
            DomainType.FINANCE,
            _MINIMAL_YAML.format(domain="finance"),
        )
        loader = ConfigLoader(configs_dir=tmp_path, cache_enabled=True)

        first = loader.load(DomainType.FINANCE)
        assert loader.cache_size() == 1

        reads = {"count": 0}
        original_read = Path.read_text

        def counting_read(self: Path, *args: object, **kwargs: object) -> str:
            if self == path:
                reads["count"] += 1
            return original_read(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", counting_read)
        second = loader.load(DomainType.FINANCE)

        assert reads["count"] == 0
        assert second.domain == first.domain
        assert second.style == first.style
        second.style = "mutated"
        third = loader.load(DomainType.FINANCE)
        assert third.style == first.style

    def test_clear_cache_forces_reload(self, tmp_path: Path) -> None:
        path = _write_domain_yaml(
            tmp_path,
            DomainType.EDUCATION,
            _MINIMAL_YAML.format(domain="education"),
        )
        loader = ConfigLoader(configs_dir=tmp_path, cache_enabled=True)
        loader.load(DomainType.EDUCATION)
        assert loader.cache_size() == 1

        path.write_text(
            _MINIMAL_YAML.format(domain="education").replace(
                "test style",
                "updated style",
            ),
            encoding="utf-8",
        )
        loader.clear_cache()
        assert loader.cache_size() == 0
        reloaded = loader.load(DomainType.EDUCATION)
        assert reloaded.style == "updated style"

    def test_cache_disabled_rereads_every_time(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = _write_domain_yaml(
            tmp_path,
            DomainType.BUSINESS,
            _MINIMAL_YAML.format(domain="business"),
        )
        loader = ConfigLoader(configs_dir=tmp_path, cache_enabled=False)
        reads = {"count": 0}
        original_read = Path.read_text

        def counting_read(self: Path, *args: object, **kwargs: object) -> str:
            if self == path:
                reads["count"] += 1
            return original_read(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", counting_read)
        loader.load(DomainType.BUSINESS)
        loader.load(DomainType.BUSINESS)
        assert reads["count"] == 2
        assert loader.cache_size() == 0


class TestDomainServicePromptContext:
    def test_get_prompt_context_uses_injected_loader(self, tmp_path: Path) -> None:
        _write_domain_yaml(
            tmp_path,
            DomainType.SCIFI,
            _MINIMAL_YAML.format(domain="scifi"),
        )
        loader = ConfigLoader(configs_dir=tmp_path, cache_enabled=True)
        service = DomainService(
            detector=_FixedDetector(DomainType.SCIFI),
            config_loader=loader,
            enrich_from_registry=False,
        )

        context = service.get_prompt_context(DomainType.SCIFI)
        assert context.domain == DomainType.SCIFI
        assert context.style == "test style"
        assert context.image_defaults["width"] == 512
