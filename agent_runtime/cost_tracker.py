"""Cost and activity ledger helpers for AgentLab."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from state_store import utc_now

# ── Pricing ──────────────────────────────────────────────────

_PRICE_CACHE: dict | None = None
_PRICE_ROOT: Path | None = None


def load_pricing(agentlab_root: Path) -> dict:
    """Load model pricing from config/model_pricing.yml.

    Returns the `models` sub-dict keyed by model name.
    Results are cached by agentlab_root.
    """
    global _PRICE_CACHE, _PRICE_ROOT
    if _PRICE_ROOT == agentlab_root and _PRICE_CACHE is not None:
        return _PRICE_CACHE
    path = agentlab_root / "config" / "model_pricing.yml"
    if not path.exists():
        _PRICE_CACHE = {}
        _PRICE_ROOT = agentlab_root
        return _PRICE_CACHE
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        raw = {}
    models = raw.get("models", {}) if isinstance(raw, dict) else {}
    currency = raw.get("currency", "USD") if isinstance(raw, dict) else "USD"
    _PRICE_CACHE = {"models": models, "currency": currency}
    _PRICE_ROOT = agentlab_root
    return _PRICE_CACHE


def _resolve_model_entry(models: dict, provider: str | None, model: str) -> tuple:
    """Resolve a pricing entry with optional provider/model combo key.

    Lookup priority:
    1. ``provider/model`` combo key (if provider is not None)
    2. plain ``model`` key

    Returns (entry_dict, matched_key) or (None, None).
    """
    if provider:
        combo_key = f"{provider}/{model}"
        if combo_key in models:
            return models[combo_key], combo_key
    if model in models:
        return models[model], model
    return None, None


def estimate_cost(
    agentlab_root: Path,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    *,
    provider: str | None = None,
) -> dict:
    """Estimate cost for a given model and token counts.

    When *provider* is supplied and a ``provider/model`` combo key exists
    in pricing, it takes priority over the plain *model* key.

    Returns a dict with:
        estimated_cost: float | None
        cost_currency: str | None
        exact_cost_available: bool
        pricing_source: str | None
    """
    pricing = load_pricing(agentlab_root)
    models = pricing.get("models", {})

    entry, _key = _resolve_model_entry(models, provider, model)
    if entry is None:
        return {
            "estimated_cost": None,
            "cost_currency": pricing.get("currency"),
            "exact_cost_available": False,
            "pricing_source": None,
        }

    input_price = entry.get("input_per_1m")
    output_price = entry.get("output_per_1m")

    # If prices are null/None, cost is unavailable
    if input_price is None or output_price is None:
        return {
            "estimated_cost": None,
            "cost_currency": pricing.get("currency"),
            "exact_cost_available": False,
            "pricing_source": "config/model_pricing.yml",
        }

    if input_tokens is None or output_tokens is None:
        return {
            "estimated_cost": None,
            "cost_currency": pricing.get("currency"),
            "exact_cost_available": False,
            "pricing_source": "config/model_pricing.yml",
        }

    cost = (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price
    return {
        "estimated_cost": round(cost, 8),
        "cost_currency": pricing.get("currency", "USD"),
        "exact_cost_available": True,
        "pricing_source": "config/model_pricing.yml",
    }


# ── Ledger helpers ───────────────────────────────────────────


def append_yaml_list(path: Path, key: str, entry: dict[str, Any]) -> Path:
    data = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault(key, [])
    data[key].append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    from atomic_io import atomic_write_text
    atomic_write_text(path, yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def usage_entry(
    project: str,
    task_id: str,
    agent_name: str,
    provider: str,
    model: str,
    status: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    notes: str = "",
    *,
    agentlab_root: Path | None = None,
) -> dict[str, Any]:
    """Build a usage-entry dict for cost_ledger append.

    When *agentlab_root* is supplied, resolves estimated cost via
    config/model_pricing.yml.
    """
    if agentlab_root is not None:
        cost_info = estimate_cost(
            agentlab_root, model, input_tokens, output_tokens, provider=provider,
        )
        estimated_cost = cost_info["estimated_cost"]
        cost_currency = cost_info["cost_currency"]
        exact_cost_available = cost_info["exact_cost_available"]
        pricing_source = cost_info["pricing_source"]
    else:
        # Legacy path – keep backward-compatible None values
        estimated_cost = None
        cost_currency = None
        exact_cost_available = provider not in {"codex_plus_manual"} and total_tokens is not None
        pricing_source = None

    return {
        "timestamp": utc_now(),
        "project": project,
        "task_id": task_id,
        "agent": agent_name,
        "provider": provider,
        "model": model,
        "status": status,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "exact_cost_available": exact_cost_available,
        "estimated_cost": estimated_cost,
        "cost_currency": cost_currency,
        "pricing_source": pricing_source,
        "notes": notes,
    }


def append_cost_ledgers(project_root: Path, run_dir: Path, entry: dict[str, Any]) -> None:
    docs = project_root / "agent_docs"
    if docs.is_symlink() and not docs.exists() and docs.with_name("agent_docs.local.bak").is_dir():
        docs = docs.with_name("agent_docs.local.bak")
    if not docs.exists() and docs.with_name("agent_docs.local.bak").is_dir():
        docs = docs.with_name("agent_docs.local.bak")
    append_yaml_list(run_dir / "cost_ledger.yml", "entries", entry)
    append_yaml_list(docs / "09_COST_LEDGER.yml", "entries", entry)