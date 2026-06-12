"""Model price resolution for CostLedger v2."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PRICE_SOURCE_CONFIG = "config/model_pricing.yml"
PRICE_SOURCES = {"provider_response", PRICE_SOURCE_CONFIG, "plugin_estimate", "unknown"}
PRICING_CONFIDENCE = {"high", "medium", "low", "none"}


@dataclass
class PriceInfo:
    model_key: str | None
    currency: str = "USD"
    input_per_1m_usd: float | None = None
    output_per_1m_usd: float | None = None
    cache_read_per_1m_usd: float | None = None
    cache_write_per_1m_usd: float | None = None
    reasoning_per_1m_usd: float | None = None
    price_source: str = "unknown"
    pricing_confidence: str = "none"
    free: bool = False

    @property
    def has_billable_text_prices(self) -> bool:
        if self.free:
            return True
        return self.input_per_1m_usd is not None and self.output_per_1m_usd is not None

    def estimate_cost_usd(
        self,
        *,
        input_tokens: int | None,
        output_tokens: int | None,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> float | None:
        """Estimate cost or return None when pricing is unknown.

        Explicit ``free: true`` is the only zero-price path. Numeric 0 values in
        legacy configs are treated as unknown unless that flag is present.
        """
        if input_tokens is None or output_tokens is None:
            return None
        if self.free:
            return 0.0
        if not self.has_billable_text_prices:
            return None
        cost = (input_tokens / 1_000_000) * float(self.input_per_1m_usd)
        cost += (output_tokens / 1_000_000) * float(self.output_per_1m_usd)
        if self.cache_read_per_1m_usd is not None:
            cost += (cache_read_tokens / 1_000_000) * float(self.cache_read_per_1m_usd)
        if self.cache_write_per_1m_usd is not None:
            cost += (cache_write_tokens / 1_000_000) * float(self.cache_write_per_1m_usd)
        if self.reasoning_per_1m_usd is not None:
            cost += (reasoning_tokens / 1_000_000) * float(self.reasoning_per_1m_usd)
        return round(cost, 8)


def _load_pricing_file(agentlab_root: Path) -> dict[str, Any]:
    path = agentlab_root / "config" / "model_pricing.yml"
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _coerce_price(value: Any, *, free: bool) -> float | None:
    if value in (None, "", "TBD", "tbd", "unknown", "UNKNOWN"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number == 0 and not free:
        return None
    return number


def _entry_confidence(entry: dict[str, Any], has_price: bool) -> str:
    confidence = str(entry.get("pricing_confidence") or "").lower()
    if confidence in PRICING_CONFIDENCE:
        return confidence
    if has_price:
        return "medium"
    return "none"


class PriceResolver:
    """Resolve model prices by alias, provider/model key, or provider id."""

    def __init__(self, agentlab_root: Path, pricing_data: dict[str, Any] | None = None) -> None:
        self.agentlab_root = agentlab_root
        self.pricing_data = pricing_data if pricing_data is not None else _load_pricing_file(agentlab_root)
        self.models = self.pricing_data.get("models", {}) if isinstance(self.pricing_data, dict) else {}
        self.default_currency = self.pricing_data.get("currency", "USD") if isinstance(self.pricing_data, dict) else "USD"

    def resolve(
        self,
        *,
        model_alias: str | None,
        provider_model_id: str | None = None,
        provider: str | None = None,
    ) -> PriceInfo:
        for key in self._candidate_keys(model_alias, provider_model_id, provider):
            entry = self.models.get(key)
            if isinstance(entry, dict):
                return self._info_from_entry(key, entry)
        return PriceInfo(model_key=None, currency=self.default_currency, price_source="unknown", pricing_confidence="none")

    def _candidate_keys(
        self,
        model_alias: str | None,
        provider_model_id: str | None,
        provider: str | None,
    ) -> list[str]:
        raw: list[str | None] = []
        if provider:
            raw.extend(
                f"{provider}/{value}"
                for value in (model_alias, provider_model_id)
                if value
            )
        raw.extend([model_alias, provider_model_id])
        candidates: list[str] = []
        for value in raw:
            if value and value not in candidates:
                candidates.append(value)
        return candidates

    def _info_from_entry(self, key: str, entry: dict[str, Any]) -> PriceInfo:
        free = bool(entry.get("free", False))
        input_price = _coerce_price(entry.get("input_per_1m_usd", entry.get("input_per_1m")), free=free)
        output_price = _coerce_price(entry.get("output_per_1m_usd", entry.get("output_per_1m")), free=free)
        has_price = free or (input_price is not None and output_price is not None)
        source = entry.get("price_source") or entry.get("pricing_source") or "manual"
        price_source = PRICE_SOURCE_CONFIG if source == "manual" else str(source)
        if price_source not in PRICE_SOURCES:
            price_source = PRICE_SOURCE_CONFIG
        return PriceInfo(
            model_key=key,
            currency=entry.get("currency") or self.default_currency or "USD",
            input_per_1m_usd=input_price,
            output_per_1m_usd=output_price,
            cache_read_per_1m_usd=_coerce_price(entry.get("cache_read_per_1m_usd"), free=free),
            cache_write_per_1m_usd=_coerce_price(entry.get("cache_write_per_1m_usd"), free=free),
            reasoning_per_1m_usd=_coerce_price(entry.get("reasoning_per_1m_usd"), free=free),
            price_source=price_source,
            pricing_confidence=_entry_confidence(entry, has_price),
            free=free,
        )
