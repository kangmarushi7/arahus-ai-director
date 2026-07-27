"""Model pricing helpers for estimated request cost."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD price per million tokens."""

    input_per_million: float = 0.0
    output_per_million: float = 0.0

    def estimate(self, *, input_tokens: int, output_tokens: int) -> float:
        """Return estimated USD cost for the given token counts."""
        inp = max(0, int(input_tokens)) / 1_000_000.0 * self.input_per_million
        out = max(0, int(output_tokens)) / 1_000_000.0 * self.output_per_million
        return round(inp + out, 8)


class PricingTable:
    """Lookup table of per-model prices with an optional default."""

    def __init__(
        self,
        prices: Mapping[str, ModelPrice] | None = None,
        *,
        default: ModelPrice | None = None,
    ) -> None:
        self._prices = {key.strip(): value for key, value in (prices or {}).items()}
        self._default = default or ModelPrice()

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object] | None) -> PricingTable:
        """Build a table from YAML ``pricing`` mapping."""
        if not raw:
            return cls()

        prices: dict[str, ModelPrice] = {}
        default: ModelPrice | None = None
        for key, value in raw.items():
            if not isinstance(value, Mapping):
                continue
            price = ModelPrice(
                input_per_million=float(value.get("input_per_million", 0.0) or 0.0),
                output_per_million=float(value.get("output_per_million", 0.0) or 0.0),
            )
            if str(key).strip().lower() == "default":
                default = price
            else:
                prices[str(key).strip()] = price
        return cls(prices, default=default)

    def get(self, model: str) -> ModelPrice:
        """Return pricing for ``model``, falling back to default."""
        cleaned = model.strip()
        if cleaned in self._prices:
            return self._prices[cleaned]
        # Free-tier suffix often shares the base model price.
        if cleaned.endswith(":free"):
            base = cleaned[: -len(":free")]
            if base in self._prices:
                return self._prices[base]
        return self._default

    def estimate(
        self,
        model: str,
        *,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Estimate USD cost for ``model`` and token counts."""
        return self.get(model).estimate(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
