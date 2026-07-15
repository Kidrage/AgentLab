"""Supplier-native pricing and immutable FX conversion for runtime routing."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


_NUMERIC_PRICING_SOURCE = "config/model_pricing.yml"
_RUNTIME_PRICE_FIELDS = (
    "input_per_1m",
    "output_per_1m",
    "cache_read_per_1m",
    "cache_write_per_1m",
    "reasoning_per_1m",
)


@dataclass(frozen=True, slots=True)
class CostQuote:
    model_id: str
    billing_mode: str
    native_amount: float | None
    native_currency: str | None
    cny_amount: float | None
    cash_basis: str
    pricing_source: str | None
    pricing_version: str | None
    fx_version: str | None
    exact: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PricingCatalog:
    """Resolve marginal task cost without rewriting supplier prices into USD."""

    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        self.data = dict(data or {})
        self.models = self.data.get("models") or {}
        self.pricing_version = str(self.data.get("version") or "") or None
        self.fx_version = str(self.data.get("active_fx_version") or "") or None
        snapshots = self.data.get("fx_snapshots") or {}
        active = snapshots.get(self.fx_version) if self.fx_version else None
        self.rates_to_cny = (active or {}).get("rates_to_cny") or {"CNY": 1.0}

    @classmethod
    def load(cls, root: Path, path: str = "config/pricing_catalog.yml") -> "PricingCatalog":
        target = Path(root) / path
        if not target.exists():
            return cls({})
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            return cls({})
        return cls(_compile_numeric_source_refs(Path(root), data))

    def convert_to_cny(self, amount: float, currency: str) -> float | None:
        try:
            rate = float(self.rates_to_cny[str(currency).upper()])
        except (KeyError, TypeError, ValueError):
            return None
        return round(float(amount) * rate, 8)

    def quote(
        self,
        model_id: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> CostQuote:
        entry = self.models.get(model_id)
        if not isinstance(entry, Mapping):
            return CostQuote(
                model_id=model_id,
                billing_mode="unknown",
                native_amount=None,
                native_currency=None,
                cny_amount=None,
                cash_basis="unknown",
                pricing_source=None,
                pricing_version=self.pricing_version,
                fx_version=self.fx_version,
                exact=False,
            )
        billing_mode = str(entry.get("billing_mode") or "unknown")
        currency = str(entry.get("currency") or "").upper() or None
        if billing_mode in {"oauth_subscription", "api_free_tier", "shell_only"}:
            return CostQuote(
                model_id=model_id,
                billing_mode=billing_mode,
                native_amount=0.0,
                native_currency=currency,
                cny_amount=0.0,
                cash_basis="marginal_task_cash",
                pricing_source=str(entry.get("source_kind") or billing_mode),
                pricing_version=self.pricing_version,
                fx_version=self.fx_version,
                exact=True,
            )
        if billing_mode != "api_metered" or not currency:
            return CostQuote(
                model_id=model_id,
                billing_mode=billing_mode,
                native_amount=None,
                native_currency=currency,
                cny_amount=None,
                cash_basis="unknown",
                pricing_source=None,
                pricing_version=self.pricing_version,
                fx_version=self.fx_version,
                exact=False,
            )

        required = (entry.get("input_per_1m"), entry.get("output_per_1m"))
        if any(value is None for value in required):
            amount = None
        else:
            amount = (max(0, input_tokens) / 1_000_000) * float(required[0])
            amount += (max(0, output_tokens) / 1_000_000) * float(required[1])
            optional = (
                (cache_read_tokens, entry.get("cache_read_per_1m")),
                (cache_write_tokens, entry.get("cache_write_per_1m")),
                (reasoning_tokens, entry.get("reasoning_per_1m")),
            )
            for tokens, price in optional:
                if tokens and price is None:
                    amount = None
                    break
                if price is not None:
                    amount += (max(0, tokens) / 1_000_000) * float(price)
        native = round(amount, 8) if amount is not None else None
        cny = self.convert_to_cny(native, currency) if native is not None else None
        return CostQuote(
            model_id=model_id,
            billing_mode=billing_mode,
            native_amount=native,
            native_currency=currency,
            cny_amount=cny,
            cash_basis="provider_metered",
            pricing_source=str(entry.get("source_ref") or "") or None,
            pricing_version=self.pricing_version,
            fx_version=self.fx_version,
            exact=native is not None and cny is not None,
        )


def _compile_numeric_source_refs(root: Path, data: Mapping[str, Any]) -> dict[str, Any]:
    """Materialize runtime prices from the single numeric pricing authority."""

    compiled = deepcopy(dict(data))
    models = compiled.get("models") or {}
    if not isinstance(models, dict):
        raise ValueError("pricing catalog models must be a mapping")
    referenced = [entry for entry in models.values() if isinstance(entry, dict) and entry.get("source_ref")]
    if not referenced:
        return compiled

    source_path = root / _NUMERIC_PRICING_SOURCE
    source = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
    if not isinstance(source, dict) or not isinstance(source.get("models"), dict):
        raise ValueError(f"invalid numeric pricing source: {_NUMERIC_PRICING_SOURCE}")
    source_models = source["models"]
    source_currency = str(source.get("currency") or "").upper()

    for runtime_model_id, entry in models.items():
        if not isinstance(entry, dict) or not entry.get("source_ref"):
            continue
        duplicate_fields = [field for field in _RUNTIME_PRICE_FIELDS if field in entry]
        if duplicate_fields:
            raise ValueError(
                f"{runtime_model_id} duplicates numeric pricing fields: {', '.join(duplicate_fields)}"
            )
        source_ref = str(entry["source_ref"])
        source_file, separator, source_key = source_ref.partition("#")
        if source_file != _NUMERIC_PRICING_SOURCE or not separator or not source_key:
            raise ValueError(f"unsupported pricing source_ref: {source_ref}")
        source_entry = source_models.get(source_key)
        if not isinstance(source_entry, Mapping):
            raise ValueError(f"unknown pricing source_ref: {source_ref}")
        expected_provider_model = str(entry.get("provider_model_id") or "")
        observed_provider_model = str(source_entry.get("provider_model_id") or "")
        if expected_provider_model and observed_provider_model != expected_provider_model:
            raise ValueError(
                f"provider model drift for {runtime_model_id}: "
                f"{expected_provider_model} != {observed_provider_model}"
            )

        currency = str(source_entry.get("currency") or source_currency).upper()
        if not currency:
            raise ValueError(f"currency missing for pricing source_ref: {source_ref}")
        entry["currency"] = currency
        for runtime_field in _RUNTIME_PRICE_FIELDS:
            source_field = f"{runtime_field}_{currency.lower()}"
            value = source_entry.get(runtime_field, source_entry.get(source_field))
            if value is not None:
                entry[runtime_field] = value
        entry["numeric_source_version"] = source.get("version")
        entry["numeric_source_verified_at"] = source_entry.get("verified_at")
    return compiled
