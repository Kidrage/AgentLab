"""Cost and activity ledger helpers for AgentLab."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from state_store import utc_now
from atomic_io import atomic_write_text
from costing.ledger import CostCall, CostLedger, render_cost_summary
from costing.pricing import PriceResolver
from costing.budget import evaluate_budget_gate, load_budget_policy, write_budget_decision

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
    for key, entry in models.items():
        if isinstance(entry, dict) and entry.get("provider_model_id") == model:
            return entry, key
    return None, None


def _coerce_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return bool(value)


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
    resolver = PriceResolver(agentlab_root, pricing)
    info = resolver.resolve(model_alias=model, provider_model_id=model, provider=provider)
    if info.model_key is None:
        return {
            "estimated_cost": None,
            "cost_currency": pricing.get("currency"),
            "exact_cost_available": False,
            "pricing_source": None,
            "pricing_confidence": "none",
        }

    cost = info.estimate_cost_usd(input_tokens=input_tokens, output_tokens=output_tokens)
    if cost is None:
        return {
            "estimated_cost": None,
            "cost_currency": info.currency,
            "exact_cost_available": False,
            "pricing_source": info.price_source if info.price_source != "unknown" else "config/model_pricing.yml",
            "pricing_confidence": info.pricing_confidence,
        }

    return {
        "estimated_cost": cost,
        "cost_currency": info.currency,
        "exact_cost_available": True,
        "pricing_source": info.price_source,
        "pricing_confidence": info.pricing_confidence,
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
    usage_source: str | None = None,
    token_estimation_method: str | None = None,
    exact_usage_available: bool | None = None,
    reported_estimated_cost: float | None = None,
    reported_cost_currency: str | None = None,
    reported_exact_cost_available: bool | None = None,
    raw_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a usage-entry dict for cost_ledger append.

    When *agentlab_root* is supplied, resolves estimated cost via
    config/model_pricing.yml.
    """
    raw_usage = raw_usage or {}
    if input_tokens is None:
        input_tokens = raw_usage.get("input_tokens") or raw_usage.get("prompt_tokens")
    if output_tokens is None:
        output_tokens = raw_usage.get("output_tokens") or raw_usage.get("completion_tokens")
    if total_tokens is None:
        total_tokens = raw_usage.get("total_tokens")
    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        total_tokens = int(input_tokens or 0) + int(output_tokens or 0)

    external_cli = provider == "agentlab-cli-executor"
    resolved_usage_source = usage_source
    if resolved_usage_source is None:
        resolved_usage_source = raw_usage.get("usage_source")
    if resolved_usage_source is None:
        if external_cli and total_tokens is not None:
            resolved_usage_source = "external_cli_estimate"
        elif input_tokens is not None or output_tokens is not None or total_tokens is not None:
            resolved_usage_source = "api_usage"
        else:
            resolved_usage_source = "unknown"
    if exact_usage_available is None:
        raw_exact_usage = raw_usage.get("exact_usage_available")
        if raw_exact_usage is not None:
            exact_usage_available = _coerce_optional_bool(raw_exact_usage)
        elif resolved_usage_source in {"api_usage", "external_cli_reported", "no_llm_call"}:
            exact_usage_available = total_tokens is not None
        else:
            exact_usage_available = False

    if reported_estimated_cost is None and raw_usage.get("estimated_cost") is not None:
        try:
            reported_estimated_cost = float(raw_usage["estimated_cost"])
        except (TypeError, ValueError):
            reported_estimated_cost = None
    if reported_cost_currency is None:
        reported_cost_currency = raw_usage.get("cost_currency") or raw_usage.get("currency")
    if reported_exact_cost_available is None and raw_usage.get("exact_cost_available") is not None:
        reported_exact_cost_available = _coerce_optional_bool(raw_usage.get("exact_cost_available"))

    if reported_estimated_cost is not None:
        estimated_cost = reported_estimated_cost
        if reported_cost_currency:
            cost_currency = reported_cost_currency
        elif agentlab_root is not None:
            cost_currency = load_pricing(agentlab_root).get("currency")
        else:
            cost_currency = None
        exact_cost_available = reported_exact_cost_available if reported_exact_cost_available is not None else bool(exact_usage_available)
        pricing_source = raw_usage.get("pricing_source") or "reported_usage"
        pricing_confidence = raw_usage.get("pricing_confidence") or ("high" if exact_cost_available else "medium")
    elif agentlab_root is not None and not external_cli:
        cost_info = estimate_cost(
            agentlab_root, model, input_tokens, output_tokens, provider=provider,
        )
        estimated_cost = cost_info["estimated_cost"]
        cost_currency = cost_info["cost_currency"]
        exact_cost_available = bool(cost_info["exact_cost_available"] and exact_usage_available)
        pricing_source = cost_info["pricing_source"]
        pricing_confidence = cost_info.get("pricing_confidence", "none")
    else:
        # Legacy path – keep backward-compatible None values
        estimated_cost = None
        cost_currency = load_pricing(agentlab_root).get("currency") if agentlab_root is not None else None
        exact_cost_available = False
        pricing_source = None
        pricing_confidence = "none"

    if reported_exact_cost_available is not None and reported_estimated_cost is None:
        exact_cost_available = bool(reported_exact_cost_available)

    unpriced_reason = None
    if estimated_cost is None:
        if not exact_usage_available:
            unpriced_reason = "usage_not_exact"
        elif pricing_source is None:
            unpriced_reason = "price_not_available"
        else:
            unpriced_reason = "cost_not_available"

    audit_fields = {
        key: raw_usage[key]
        for key in (
            "billing_mode",
            "capacity_primary_route",
            "capacity_route_id",
            "capacity_pool_id",
            "capacity_status",
            "capacity_selection_kind",
            "capacity_attempt_id",
            "capacity_failure_class",
            "capacity_reset_at",
            "capacity_remaining",
            "capacity_evidence_source",
            "capacity_confidence",
            "failure_class",
            "configured_cli_agent",
            "cli_agent",
            "provider_reported_model_id",
            "provider_reported_model_ids",
            "provider_reported_session_id",
        )
        if key in raw_usage
    }

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
        "exact_usage_available": exact_usage_available,
        "exact_cost_available": exact_cost_available,
        "estimated_cost": estimated_cost,
        "cost_currency": cost_currency,
        "pricing_source": pricing_source,
        "pricing_confidence": pricing_confidence,
        "usage_source": resolved_usage_source,
        **({"token_estimation_method": token_estimation_method} if token_estimation_method else {}),
        **({"unpriced_reason": unpriced_reason} if unpriced_reason else {}),
        **audit_fields,
        "notes": notes,
    }


def append_cost_ledgers(project_root: Path, run_dir: Path, entry: dict[str, Any]) -> None:
    docs = project_root / "agent_docs"
    if docs.is_symlink() and not docs.exists() and docs.with_name("agent_docs.local.bak").is_dir():
        docs = docs.with_name("agent_docs.local.bak")
    if not docs.exists() and docs.with_name("agent_docs.local.bak").is_dir():
        docs = docs.with_name("agent_docs.local.bak")
    run_ledger_path = append_yaml_list(run_dir / "cost_ledger.yml", "entries", entry)
    _refresh_v2_run_cost_artifacts(run_ledger_path)
    append_yaml_list(docs / "09_COST_LEDGER.yml", "entries", entry)


def _call_from_legacy_entry(entry: dict[str, Any]) -> CostCall:
    return CostCall(
        stage=str(entry.get("stage") or entry.get("node") or entry.get("agent") or "unknown"),
        agent=str(entry.get("agent") or "unknown"),
        provider=entry.get("provider"),
        model_alias=entry.get("model") or entry.get("model_alias"),
        provider_model_id=entry.get("provider_model_id"),
        input_tokens=int(entry.get("input_tokens") or 0),
        output_tokens=int(entry.get("output_tokens") or 0),
        cache_read_tokens=int(entry.get("cache_read_tokens") or 0),
        cache_write_tokens=int(entry.get("cache_write_tokens") or 0),
        reasoning_tokens=int(entry.get("reasoning_tokens") or 0),
        image_input_tokens=int(entry.get("image_input_tokens") or 0),
        audio_input_tokens=int(entry.get("audio_input_tokens") or 0),
        usage_source=entry.get("usage_source") or ("api_usage" if entry.get("input_tokens") is not None else "unknown"),
        exact_usage_available=bool(_coerce_optional_bool(entry.get("exact_usage_available", entry.get("usage_source") in {"api_usage", "external_cli_reported", "no_llm_call"}))),
        price_source=entry.get("pricing_source") or "unknown",
        estimated_cost_usd=entry.get("estimated_cost"),
        exact_cost_available=bool(_coerce_optional_bool(entry.get("exact_cost_available", entry.get("estimated_cost") is not None))),
        pricing_confidence=entry.get("pricing_confidence") or ("high" if entry.get("exact_cost_available") else "none"),
        token_estimation_method=entry.get("token_estimation_method"),
        unpriced_reason=entry.get("unpriced_reason"),
        started_at=entry.get("started_at") or entry.get("timestamp"),
        finished_at=entry.get("finished_at"),
    )


def _refresh_v2_run_cost_artifacts(run_ledger_path: Path) -> None:
    try:
        data = yaml.safe_load(run_ledger_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return
    entries = data.get("entries") or []
    if not isinstance(entries, list):
        return
    task_id = ""
    if entries:
        task_id = str(entries[-1].get("task_id") or "")
    if not task_id:
        task_id = run_ledger_path.parent.name
    ledger = CostLedger(
        task_id=task_id,
        currency=str(data.get("currency") or "USD"),
        calls=[_call_from_legacy_entry(item) for item in entries if isinstance(item, dict)],
    )
    v2 = ledger.as_dict()
    merged = dict(data)
    merged.update(v2)
    merged["entries"] = entries
    atomic_write_text(
        run_ledger_path,
        yaml.safe_dump(merged, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    atomic_write_text(run_ledger_path.with_name("cost_summary.md"), render_cost_summary(ledger), encoding="utf-8")
    try:
        agentlab_root = run_ledger_path.parents[3]
        policy = load_budget_policy(agentlab_root)
    except Exception:
        policy = None
    decision = evaluate_budget_gate(ledger, policy)
    write_budget_decision(run_ledger_path.parent, decision)
