"""Deterministic prompt section templates and ordering."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.prompt.models import PromptComponents

# Positive prompt section order is fixed for stable, reproducible output.
POSITIVE_SECTION_ORDER: tuple[str, ...] = (
    "subject",
    "action",
    "environment",
    "camera",
    "lighting",
    "composition",
    "style",
    "extra_details",
    "quality_tags",
)

SECTION_SEPARATOR = ", "


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """Declares how :class:`PromptComponents` map into a positive prompt string.

    Ordering is intentional and stable. Changing ``section_order`` is the
    supported way to adjust layout without altering merge logic.
    """

    section_order: tuple[str, ...] = POSITIVE_SECTION_ORDER
    separator: str = SECTION_SEPARATOR
    quality_tag_separator: str = ", "
    # Fields treated as comma-separated tag bags when merging / deduping.
    tag_fields: tuple[str, ...] = field(
        default_factory=lambda: ("quality_tags", "negative_prompt")
    )

    def sections(self, components: PromptComponents) -> list[tuple[str, str]]:
        """Return ``(section_name, text)`` pairs in template order.

        Empty sections are omitted. ``quality_tags`` are joined with
        :attr:`quality_tag_separator`.
        """
        data = components.model_dump()
        ordered: list[tuple[str, str]] = []
        for name in self.section_order:
            if name not in data:
                continue
            raw = data[name]
            if name == "quality_tags":
                tags = [str(tag).strip() for tag in (raw or []) if str(tag).strip()]
                text = self.quality_tag_separator.join(tags)
            else:
                text = str(raw or "").strip()
            if text:
                ordered.append((name, text))
        return ordered

    def render_positive(self, components: PromptComponents) -> str:
        """Render the positive prompt from non-empty sections."""
        return self.separator.join(text for _, text in self.sections(components))


DEFAULT_TEMPLATE = PromptTemplate()
