"""User-facing model configuration commands."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable
import fcntl
import hashlib
import re

import typer
import yaml
from rich.console import Console
from rich.table import Table

from agent_runtime.role_keys import (
    CAPACITY_ROLE_ALIASES,
    ROLE_KEY_TO_CANONICAL,
    normalize_role_key,
)


MODE_TO_TIER = {
    "alter": "alter",
    "altered": "alter",
    "quality": "full",
    "balanced": "performance",
    "frugal": "low",
    "full": "full",
    "performance": "performance",
    "low": "low",
}

INLINE_NUMERIC_PRICE_RE = re.compile(
    r"(?:[$\u00a5\uffe5]\s*\d+(?:\.\d+)?|\b(?:USD|CNY)\s*\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _read_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return yaml.safe_load(path.read_text(encoding="utf-8")) or default


def _write_yaml(path: Path, data: Any) -> None:
    try:
        from agent_runtime.atomic_io import atomic_write_yaml
    except ModuleNotFoundError:  # pragma: no cover - direct script path
        from atomic_io import atomic_write_yaml

    atomic_write_yaml(path, data, sort_keys=False, allow_unicode=True)


def _role_key(role: str) -> str:
    return normalize_role_key(role)


def _proposal_dir(root: Path) -> Path:
    return root / ".agentlab" / "model_proposals"


def _serialized_model_config_write(
    root: Path,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Serialize proposal application so hash checks and writes form one CAS."""

    def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(function)
        def locked(*args: Any, **kwargs: Any) -> Any:
            lock_path = _proposal_dir(root) / ".apply.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a+", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    return function(*args, **kwargs)
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

        return locked

    return decorator


def _proposal_id(role: str, cli: str, model: str) -> str:
    seed = f"{datetime.now(timezone.utc).isoformat()}:{role}:{cli}:{model}".encode()
    return "model_" + hashlib.sha1(seed).hexdigest()[:12]


def _mapping_sha256(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    payload = yaml.safe_dump(
        value,
        sort_keys=True,
        allow_unicode=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_catalog_model_entry(
    root: Path,
    model_key: str,
    entry: Any,
) -> str | None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", model_key):
        return "model key must use lowercase letters, digits, and underscores"
    if not isinstance(entry, dict):
        return "model catalog entry must be a YAML mapping"
    provider = str(entry.get("provider") or "").strip()
    model_id = str(entry.get("model_id") or "").strip()
    if not provider:
        return "model catalog entry requires provider"
    if not model_id:
        return "model catalog entry requires model_id"
    catalog = _read_yaml(root / "config" / "model_catalog.yml", {}) or {}
    if provider not in (catalog.get("providers") or {}):
        return f"unknown model provider: {provider}"
    capacity_pool = str(entry.get("capacity_pool") or "").strip()
    if capacity_pool:
        capacity = _read_yaml(root / "config" / "model_capacity.yml", {}) or {}
        if capacity_pool not in (capacity.get("pools") or {}):
            return f"unknown capacity pool: {capacity_pool}"
    reasoning_effort = str(entry.get("reasoning_effort") or "").strip()
    if reasoning_effort and reasoning_effort not in {
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    }:
        return (
            "reasoning_effort must be minimal, low, medium, high, or xhigh "
            "when declared"
        )
    return None


def _governed_proposal_binding(
    root: Path,
    *,
    role_key: str,
    cli_agent: str,
    model_key: str,
    tier: str,
) -> tuple[dict[str, str] | None, str | None]:
    """Resolve a proposal only through an existing capacity/contract/binding route."""
    canonical_role = ROLE_KEY_TO_CANONICAL.get(role_key)
    if not canonical_role:
        return None, f"Unknown canonical role: {role_key}"
    catalog = _read_yaml(root / "config" / "model_catalog.yml", {}) or {}
    if model_key not in (catalog.get("models") or {}):
        return None, f"Unknown model catalog key: {model_key}"

    try:
        from agent_runtime.protocols import check_role_binding
    except ModuleNotFoundError:  # pragma: no cover - direct script path
        from protocols import check_role_binding

    binding_allowed, binding_reason = check_role_binding(root, cli_agent, canonical_role)
    if not binding_allowed:
        return None, f"Protocol role binding rejected: {binding_reason}"

    capacity = _read_yaml(root / "config" / "model_capacity.yml", {}) or {}
    capacity_role = CAPACITY_ROLE_ALIASES.get(role_key, role_key)
    matches: list[tuple[str, dict[str, Any]]] = []
    for route_id, route in (capacity.get("routes") or {}).items():
        if not isinstance(route, dict):
            continue
        if (
            _role_key(str(route.get("role") or "")) == capacity_role
            and str(route.get("worker") or "") == cli_agent
            and str(route.get("model_key") or "") == model_key
        ):
            matches.append((str(route_id), route))
    if not matches:
        return None, (
            "No governed capacity route matches "
            f"role={role_key}, cli={cli_agent}, model={model_key}"
        )

    contracts = (
        _read_yaml(root / "config" / "worker_invocation_contracts.yml", {}) or {}
    ).get("contracts") or {}
    valid: list[tuple[str, dict[str, Any], str]] = []
    for route_id, route in matches:
        contract_id = str(route.get("invocation_contract") or "")
        contract = contracts.get(contract_id) or {}
        if str(contract.get("worker_id") or "") == cli_agent:
            valid.append((route_id, route, contract_id))
    if not valid:
        return None, "Matching capacity route has no worker-compatible invocation contract"

    def route_rank(item: tuple[str, dict[str, Any], str]) -> tuple[int, str]:
        route_id = item[0].lower()
        low_route = route_id.endswith("low")
        return (0 if (tier == "low") == low_route else 1, route_id)

    route_id, _route, contract_id = sorted(valid, key=route_rank)[0]
    return {
        "capacity_route": route_id,
        "invocation_contract": contract_id,
    }, None


def _tier(mode: str) -> str:
    normalized = str(mode or "balanced").lower()
    if normalized not in MODE_TO_TIER:
        raise typer.BadParameter(
            "mode must be alter, quality, balanced, frugal, full, performance, or low"
        )
    return MODE_TO_TIER[normalized]


def _mode_config(agent_model_profiles: dict[str, Any], mode: str) -> dict[str, Any]:
    tier = _tier(mode)
    default_mode = str(agent_model_profiles.get("default_mode") or "full_cli")
    modes = agent_model_profiles.get("modes") or {}
    return ((modes.get(default_mode) or {}).get("tiers") or {}).get(tier) or {}


def _catalog_entry(catalog: dict[str, Any], model_key: str) -> dict[str, Any]:
    return ((catalog.get("models") or {}).get(model_key) or {}) if model_key else {}


def _provider_entry(catalog: dict[str, Any], model_entry: dict[str, Any]) -> dict[str, Any]:
    provider = str(model_entry.get("provider") or "")
    return ((catalog.get("providers") or {}).get(provider) or {}) if provider else {}


def _cost_source(model_entry: dict[str, Any], provider_entry: dict[str, Any]) -> str:
    pricing_key = str(model_entry.get("pricing_key") or "").strip()
    if pricing_key:
        return f"config/model_pricing.yml#{pricing_key}"
    pricing = model_entry.get("pricing") or {}
    billing = pricing.get("billing_source") or pricing.get("currency") or provider_entry.get("currency")
    if not billing:
        return "unknown"
    if billing == "token_plan":
        return "subscription/token plan"
    if billing in {"codex_oauth", "codex_cli_oauth", "grok_oauth"}:
        return "oauth/subscription quota"
    if billing == "agy_oauth":
        return "oauth/subscription quota"
    if billing == "gemini_api_key":
        return "free-tier/api quota"
    return f"pay-as-you-go/{billing}"


def _risk(model_key: str, model_entry: dict[str, Any]) -> str:
    weaknesses = ", ".join(str(item) for item in model_entry.get("weaknesses") or [])
    if model_key.startswith("qwen3_7") or model_key.startswith("qwen3_6_plus"):
        return weaknesses or "higher cost; use only when the task needs Qwen strengths"
    return weaknesses or "normal"


def _numeric_paths(value: Any, path: tuple[str, ...] = ()) -> list[str]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [".".join(path)]
    if isinstance(value, dict):
        paths: list[str] = []
        for key, nested in value.items():
            paths.extend(_numeric_paths(nested, (*path, str(key))))
        return paths
    if isinstance(value, list):
        paths = []
        for index, nested in enumerate(value):
            paths.extend(_numeric_paths(nested, (*path, str(index))))
        return paths
    return []


def _numeric_pricing_paths(entry: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key, value in entry.items():
        normalized = str(key).lower()
        if "usd" in normalized or normalized in {"input_per_1m", "output_per_1m"}:
            paths.extend(_numeric_paths(value, (str(key),)))
    return paths


def _capacity_rows(root: Path, ledger_path: Path | None = None) -> list[dict[str, Any]]:
    policy = _read_yaml(root / "config" / "model_capacity.yml", {}) or {}
    ledger = _read_yaml(ledger_path, {}) if ledger_path else {}
    ledger_pools = (ledger or {}).get("pools") or {}
    rows: list[dict[str, Any]] = []
    for pool_id, pool in sorted((policy.get("pools") or {}).items()):
        state = ledger_pools.get(pool_id) or {}
        declared = pool.get("declared_windows") or {}
        rows.append(
            {
                "pool_id": pool_id,
                "provider": pool.get("provider"),
                "billing_mode": pool.get("billing_mode"),
                "status": state.get("status") or "unknown",
                "failure_class": state.get("failure_class"),
                "remaining": state.get("remaining"),
                "reset_at": state.get("reset_at"),
                "rolling_period_seconds": (declared.get("rolling") or {}).get(
                    "period_seconds"
                ),
                "weekly_period_seconds": (declared.get("weekly") or {}).get(
                    "period_seconds"
                ),
                "probe": pool.get("probe"),
                "probe_capability": pool.get("probe_capability")
                or {
                    "kind": "none",
                    "reports_remaining": False,
                    "reports_reset_at": False,
                },
            }
        )
    return rows


def _role_rows(root: Path, *, mode: str, role: str | None) -> list[dict[str, str]]:
    profiles = _read_yaml(root / "config" / "agent_model_profiles.yml", {}) or {}
    catalog = _read_yaml(root / "config" / "model_catalog.yml", {}) or {}
    capacity = _read_yaml(root / "config" / "model_capacity.yml", {}) or {}
    tier_cfg = _mode_config(profiles, mode)
    selected_role = _role_key(role) if role else None
    rows: list[dict[str, str]] = []
    for role_key, cfg in sorted(tier_cfg.items()):
        if selected_role and role_key != selected_role:
            continue
        if isinstance(cfg, str):
            rows.append({
                "role": role_key,
                "cli": "skip",
                "model": cfg,
                "provider": "",
                "cost": "",
                "pool": "",
                "fallback": "",
                "fit": "role skipped in this mode",
                "risk": "",
            })
            continue
        if not isinstance(cfg, dict):
            continue
        model_key = str(cfg.get("default") or cfg.get("provider") or "")
        model_entry = _catalog_entry(catalog, model_key)
        provider_entry = _provider_entry(catalog, model_entry)
        capacity_route_id = str(cfg.get("capacity_route") or "")
        capacity_route = (capacity.get("routes") or {}).get(capacity_route_id) or {}
        approved_fallbacks = capacity_route.get("approved_fallbacks") or []
        rows.append({
            "role": role_key,
            "cli": str(cfg.get("cli_agent") or cfg.get("executor_type") or "direct_api"),
            "model": model_key,
            "provider": str(model_entry.get("provider") or cfg.get("provider") or ""),
            "cost": _cost_source(model_entry, provider_entry),
            "pool": str(capacity_route.get("pool") or ""),
            "fallback": (
                ",".join(str(item) for item in approved_fallbacks)
                if capacity_route_id
                else str(cfg.get("fallback") or cfg.get("fallback_cli_agent") or "")
            ),
            "fit": ", ".join(str(item) for item in model_entry.get("suitable_agents") or [])[:80],
            "risk": _risk(model_key, model_entry),
        })
    return rows


def _render_rows(console: Console, rows: list[dict[str, str]]) -> None:
    table = Table()
    table.add_column("Role", no_wrap=True)
    table.add_column("CLI/API", no_wrap=True)
    table.add_column("Model", overflow="fold")
    table.add_column("Provider", overflow="fold")
    table.add_column("Cost", overflow="fold")
    table.add_column("Capacity pool", overflow="fold")
    table.add_column("Fallback", overflow="fold")
    table.add_column("Fit", overflow="fold")
    table.add_column("Risk", overflow="fold")
    for row in rows:
        table.add_row(
            row["role"],
            row["cli"],
            row["model"],
            row["provider"],
            row["cost"],
            row["pool"],
            row["fallback"],
            row["fit"],
            row["risk"],
        )
    console.print(table)
    for row in rows:
        console.print(
            " | ".join(
                [
                    f"role={row['role']}",
                    f"cli_api={row['cli']}",
                    f"model={row['model']}",
                    f"provider={row['provider']}",
                    f"cost={row['cost']}",
                    f"capacity_pool={row['pool']}",
                    f"fallback={row['fallback']}",
                    f"fit={row['fit']}",
                    f"risk={row['risk']}",
                ]
            )
        )


def _doctor_issues(root: Path) -> list[dict[str, str]]:
    profiles = _read_yaml(root / "config" / "agent_model_profiles.yml", {}) or {}
    catalog = _read_yaml(root / "config" / "model_catalog.yml", {}) or {}
    capacity = _read_yaml(root / "config" / "model_capacity.yml", {}) or {}
    invocation_contracts = _read_yaml(
        root / "config" / "worker_invocation_contracts.yml", {}
    ) or {}
    pricing = _read_yaml(root / "config" / "model_pricing.yml", {}) or {}
    provider_registry = _read_yaml(root / "config" / "model_providers.yml", {}) or {}
    media_backends = _read_yaml(
        root / "config" / "media_generation_backends.yml", {}
    ) or {}
    visual = _read_yaml(root / "config" / "visual_acceptance.yml", {}) or {}
    issues: list[dict[str, str]] = []
    modes = profiles.get("modes") or {}
    for mode_name, mode_cfg in modes.items():
        tiers = (mode_cfg or {}).get("tiers") or {}
        for tier_name in ("performance", "low"):
            for role, cfg in (tiers.get(tier_name) or {}).items():
                if not isinstance(cfg, dict):
                    continue
                for field in ("default", "fallback"):
                    value = str(cfg.get(field) or "")
                    if value.startswith("qwen3_7_max") or (tier_name == "low" and value.startswith("qwen3_6_plus")):
                        issues.append({
                            "severity": "warning",
                            "scope": f"{mode_name}.{tier_name}.{role}.{field}",
                            "issue": "high_qwen_default_in_balanced_or_frugal",
                            "value": value,
                        })

    capacity_routes = capacity.get("routes") or {}
    pools = capacity.get("pools") or {}
    catalog_models = catalog.get("models") or {}
    pricing_models = pricing.get("models") or {}
    contracts = invocation_contracts.get("contracts") or {}
    for tier_name, tier in (
        (((profiles.get("modes") or {}).get("full_cli") or {}).get("tiers") or {}).items()
    ):
        for role, cfg in (tier or {}).items():
            if not isinstance(cfg, dict) or not cfg.get("capacity_route"):
                continue
            route_id = str(cfg["capacity_route"])
            route = capacity_routes.get(route_id)
            scope = f"full_cli.{tier_name}.{role}.capacity_route"
            if not isinstance(route, dict):
                issues.append({
                    "severity": "error",
                    "scope": scope,
                    "issue": "missing_capacity_route",
                    "value": route_id,
                })
                continue
            expected = {
                "role": CAPACITY_ROLE_ALIASES.get(role, role),
                "worker": cfg.get("cli_agent"),
                "invocation_contract": cfg.get("invocation_contract"),
                "model_key": cfg.get("default"),
            }
            mismatches = [
                key for key, value in expected.items() if route.get(key) != value
            ]
            if mismatches:
                issues.append({
                    "severity": "error",
                    "scope": scope,
                    "issue": "capacity_route_profile_mismatch",
                    "value": ",".join(mismatches),
                })

    for route_id, route in capacity_routes.items():
        model_key = str((route or {}).get("model_key") or "")
        pool_id = str((route or {}).get("pool") or "")
        contract_id = str((route or {}).get("invocation_contract") or "")
        worker_id = str((route or {}).get("worker") or "")
        model_entry = catalog_models.get(model_key) or {}
        pool = pools.get(pool_id) or {}
        contract = contracts.get(contract_id)
        if model_key not in catalog_models:
            issues.append({
                "severity": "error",
                "scope": f"model_capacity.routes.{route_id}.model_key",
                "issue": "capacity_model_missing_from_catalog",
                "value": model_key,
            })
        if pool_id not in pools:
            issues.append({
                "severity": "error",
                "scope": f"model_capacity.routes.{route_id}.pool",
                "issue": "capacity_pool_missing",
                "value": pool_id,
            })
        if not isinstance(contract, dict):
            issues.append({
                "severity": "error",
                "scope": f"model_capacity.routes.{route_id}.invocation_contract",
                "issue": "capacity_contract_missing",
                "value": contract_id,
            })
        elif str(contract.get("worker_id") or "") != worker_id:
            issues.append({
                "severity": "error",
                "scope": f"model_capacity.routes.{route_id}.invocation_contract",
                "issue": "capacity_contract_worker_mismatch",
                "value": f"route={worker_id},contract={contract.get('worker_id')}",
            })
        declared_model_pool = str(model_entry.get("capacity_pool") or "")
        if declared_model_pool and declared_model_pool != pool_id:
            issues.append({
                "severity": "error",
                "scope": f"model_capacity.routes.{route_id}.pool",
                "issue": "capacity_model_pool_mismatch",
                "value": f"route={pool_id},model={declared_model_pool}",
            })
        model_provider = str(model_entry.get("provider") or "")
        pool_provider = str(pool.get("provider") or "")
        if model_provider and pool_provider and model_provider != pool_provider:
            issues.append({
                "severity": "error",
                "scope": f"model_capacity.routes.{route_id}.pool",
                "issue": "capacity_pool_provider_mismatch",
                "value": f"model={model_provider},pool={pool_provider}",
            })

    for pool_id, pool in pools.items():
        pending: list[tuple[tuple[str, ...], Any]] = [((), pool)]
        while pending:
            path, value = pending.pop()
            if not isinstance(value, dict):
                continue
            for key, nested in value.items():
                nested_path = (*path, str(key))
                scope = f"model_capacity.pools.{pool_id}.{'/'.join(nested_path)}"
                if str(key).startswith("exhaustion_cooldown"):
                    issues.append({
                        "severity": "error",
                        "scope": scope,
                        "issue": "static_exhaustion_cooldown_forbidden",
                        "value": str(nested),
                    })
                if str(key) in {"limit", "remaining", "reset", "reset_at"} and nested is not None:
                    issues.append({
                        "severity": "error",
                        "scope": scope,
                        "issue": "static_capacity_value_must_be_unknown",
                        "value": str(nested),
                    })
                if isinstance(nested, dict):
                    pending.append((nested_path, nested))

    pricing_authority = pricing.get("authority") or {}
    if pricing and (
        pricing_authority.get("numeric_runtime_pricing")
        != "config/model_pricing.yml"
        or pricing_authority.get("duplicate_numeric_pricing_elsewhere_forbidden")
        is not True
    ):
        issues.append({
            "severity": "error",
            "scope": "model_pricing.authority",
            "issue": "pricing_authority_missing",
            "value": str(pricing_authority),
        })

    for model_key, model_entry in catalog_models.items():
        if not isinstance(model_entry, dict):
            continue
        pricing_key = str(model_entry.get("pricing_key") or "").strip()
        if pricing_key and pricing_key not in pricing_models:
            issues.append({
                "severity": "error",
                "scope": f"model_catalog.models.{model_key}.pricing_key",
                "issue": "pricing_key_missing",
                "value": pricing_key,
            })
        duplicate_paths = _numeric_paths(
            model_entry.get("pricing") or {},
            ("pricing",),
        )
        if duplicate_paths:
            issues.append({
                "severity": "error",
                "scope": f"model_catalog.models.{model_key}.pricing",
                "issue": "duplicate_numeric_pricing_outside_authority",
                "value": ",".join(duplicate_paths),
            })

    for provider_id, provider_entry in (
        (provider_registry.get("providers") or {}).items()
    ):
        if not isinstance(provider_entry, dict):
            continue
        pricing_key = str(provider_entry.get("pricing_key") or "").strip()
        if pricing_key and pricing_key not in pricing_models:
            issues.append({
                "severity": "error",
                "scope": f"model_providers.providers.{provider_id}.pricing_key",
                "issue": "pricing_key_missing",
                "value": pricing_key,
            })
        duplicate_paths = _numeric_paths(
            provider_entry.get("pricing") or {},
            ("pricing",),
        )
        if duplicate_paths:
            issues.append({
                "severity": "error",
                "scope": f"model_providers.providers.{provider_id}.pricing",
                "issue": "duplicate_numeric_pricing_outside_authority",
                "value": ",".join(duplicate_paths),
            })
        notes = provider_entry.get("notes") or []
        notes_text = "\n".join(str(item) for item in notes) if isinstance(notes, list) else str(notes)
        if INLINE_NUMERIC_PRICE_RE.search(notes_text):
            issues.append({
                "severity": "error",
                "scope": f"model_providers.providers.{provider_id}.notes",
                "issue": "inline_numeric_provider_pricing_forbidden",
                "value": "numeric currency amount",
            })

    for pricing_key, pricing_entry in pricing_models.items():
        if not isinstance(pricing_entry, dict) or not _numeric_pricing_paths(pricing_entry):
            continue
        if not pricing_entry.get("source_url"):
            issues.append({
                "severity": "error",
                "scope": f"model_pricing.models.{pricing_key}.source_url",
                "issue": "numeric_pricing_source_missing",
                "value": pricing_key,
            })
        if not pricing_entry.get("verified_at"):
            issues.append({
                "severity": "error",
                "scope": f"model_pricing.models.{pricing_key}.verified_at",
                "issue": "numeric_pricing_verification_missing",
                "value": pricing_key,
            })

    for backend_id, backend in (media_backends.get("backends") or {}).items():
        if not isinstance(backend, dict):
            continue
        model_references: list[tuple[str, str]] = []
        for registry_name in ("models", "registered_generation_models"):
            for modality, model_id_value in (
                backend.get(registry_name) or {}
            ).items():
                model_ids = (
                    model_id_value
                    if isinstance(model_id_value, list)
                    else [model_id_value]
                )
                for index, value in enumerate(model_ids):
                    if registry_name == "models" and str(value).strip() == "skill_auto":
                        # Dynamic skill routes price their explicit allow-list below;
                        # the routing sentinel is not itself a billable model.
                        continue
                    suffix = f".{index}" if isinstance(model_id_value, list) else ""
                    model_references.append(
                        (
                            "media_generation_backends.backends."
                            f"{backend_id}.{registry_name}.{modality}{suffix}",
                            str(value or "").strip(),
                        )
                    )
        for scope, model_id in model_references:
            pricing_entry = pricing_models.get(model_id)
            if not isinstance(pricing_entry, dict):
                issues.append({
                    "severity": "error",
                    "scope": scope,
                    "issue": "media_backend_pricing_missing",
                    "value": model_id,
                })
                continue
            if str(pricing_entry.get("provider_model_id") or "") != model_id:
                issues.append({
                    "severity": "error",
                    "scope": scope,
                    "issue": "media_backend_pricing_model_id_mismatch",
                    "value": model_id,
                })
            subscription_media_pricing = (
                pricing_entry.get("billing_mode") in {"subscription", "subscription_or_quota"}
                and pricing_entry.get("numeric_pricing_applicable") is False
            )
            if not subscription_media_pricing and not _numeric_paths(
                pricing_entry.get("media_unit_prices_usd") or {},
                ("media_unit_prices_usd",),
            ):
                issues.append({
                    "severity": "error",
                    "scope": scope,
                    "issue": "media_backend_unit_pricing_missing",
                    "value": model_id,
                })

    if capacity and ["hermes", "status", "--all"] not in (
        (capacity.get("probe_policy") or {}).get("forbidden_commands") or []
    ):
        issues.append({
            "severity": "error",
            "scope": "model_capacity.probe_policy",
            "issue": "unsafe_hermes_status_probe_not_forbidden",
            "value": "hermes status --all",
        })

    if catalog and not catalog.get("last_verified"):
        issues.append({
            "severity": "error",
            "scope": "model_catalog.last_verified",
            "issue": "missing_model_fact_verification_date",
            "value": "",
        })
    if pricing and not pricing.get("last_verified"):
        issues.append({
            "severity": "error",
            "scope": "model_pricing.last_verified",
            "issue": "missing_pricing_verification_date",
            "value": "",
        })

    visual_policy = visual.get("visual_acceptance") or {}
    review = visual_policy.get("review") or {}
    boundary = visual_policy.get("boundary") or {}
    if visual and not (
        boundary.get("module_may_promote") is False
        and boundary.get("promotion_requires_external_gate") is True
        and review.get("require_distinct_reviewer_ids") is True
        and review.get("forbid_producer_identity_backend_or_model") is True
    ):
        issues.append({
            "severity": "error",
            "scope": "visual_acceptance",
            "issue": "independent_visual_acceptance_boundary_missing",
            "value": "",
        })
    return issues


def register_model_commands(app: typer.Typer, project_root: Path, console: Console) -> None:
    models_app = typer.Typer(help="Show, propose, apply, and audit model routing.", no_args_is_help=True)

    @models_app.command("show")
    def show_models(
        role: str | None = typer.Option(None, "--role", help="Limit output to one role, e.g. Writer."),
        mode: str = typer.Option("alter", "--mode", help="alter, quality, balanced, or frugal."),
    ) -> None:
        """Show role model routing with cost source and risks."""
        rows = _role_rows(project_root, mode=mode, role=role)
        _render_rows(console, rows)
        if role and not rows:
            raise typer.Exit(code=1)

    @models_app.command("plan")
    def plan_models(
        mode: str = typer.Option(..., "--mode", help="alter, quality, balanced, or frugal."),
    ) -> None:
        """Preview the model plan for a quality/cost mode."""
        rows = _role_rows(project_root, mode=mode, role=None)
        console.print({"mode": mode, "tier": _tier(mode), "status": "preview_only"})
        _render_rows(console, rows)

    @models_app.command("propose")
    def propose_model(
        role: str = typer.Option(..., "--role", help="Role to change, e.g. Writer."),
        cli: str = typer.Option(..., "--cli", help="CLI/API worker id, e.g. agy."),
        model: str = typer.Option(..., "--model", help="Model catalog key, e.g. deepseek_v4_flash."),
        mode: str = typer.Option("alter", "--mode", help="alter, quality, balanced, or frugal."),
        all_tiers: bool = typer.Option(
            False,
            "--all-tiers",
            help="Apply the governed route proposal to alter, full, performance, and low.",
        ),
    ) -> None:
        """Create a model-routing proposal without changing config."""
        catalog = _read_yaml(project_root / "config" / "model_catalog.yml", {}) or {}
        if model not in (catalog.get("models") or {}):
            console.print(f"[red]Unknown model catalog key: {model}[/red]")
            raise typer.Exit(code=1)
        role_key = _role_key(role)
        tiers = ["alter", "full", "performance", "low"] if all_tiers else [_tier(mode)]
        bindings: dict[str, dict[str, str]] = {}
        for tier in tiers:
            binding, issue = _governed_proposal_binding(
                project_root,
                role_key=role_key,
                cli_agent=cli,
                model_key=model,
                tier=tier,
            )
            if issue or binding is None:
                console.print(
                    f"[red]{tier}: {issue or 'Invalid governed model route'}[/red]"
                )
                raise typer.Exit(code=1)
            bindings[tier] = binding
        profiles = _read_yaml(
            project_root / "config" / "agent_model_profiles.yml",
            {},
        ) or {}
        proposal_id = _proposal_id(role, cli, model)
        proposal = {
            "schema_version": 1,
            "proposal_id": proposal_id,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "target_file": "config/agent_model_profiles.yml",
            "mode": mode,
            "tier": tiers[0] if len(tiers) == 1 else None,
            "tiers": tiers,
            "role": role_key,
            "cli_agent": cli,
            "model": model,
            "bindings": bindings,
            "invocation_contract": (
                bindings[tiers[0]]["invocation_contract"]
                if len(tiers) == 1
                else None
            ),
            "capacity_route": (
                bindings[tiers[0]]["capacity_route"]
                if len(tiers) == 1
                else None
            ),
            "profiles_sha256_before": _mapping_sha256(profiles),
            "requires_agentlab_apply": True,
            "frontdesk_may_apply": False,
        }
        _write_yaml(_proposal_dir(project_root) / f"{proposal_id}.yml", proposal)
        console.print(yaml.safe_dump(proposal, sort_keys=False, allow_unicode=True).rstrip())

    @models_app.command("apply")
    @_serialized_model_config_write(project_root)
    def apply_model_proposal(
        proposal: str = typer.Option(..., "--proposal", help="Proposal id from models propose."),
    ) -> None:
        """Apply an explicit pending model proposal."""
        path = _proposal_dir(project_root) / f"{proposal}.yml"
        data = _read_yaml(path, {}) or {}
        if not data or data.get("proposal_id") != proposal:
            console.print(f"[red]Unknown proposal id: {proposal}[/red]")
            raise typer.Exit(code=1)
        proposal_status = str(data.get("status") or "")
        if proposal_status not in {"pending", "applying"}:
            console.print(f"[red]Proposal is not pending/applying: {proposal}[/red]")
            raise typer.Exit(code=1)
        profiles_path = project_root / "config" / "agent_model_profiles.yml"
        profiles = _read_yaml(profiles_path, {}) or {}
        current_profiles_sha256 = _mapping_sha256(profiles)
        mode_name = str(profiles.get("default_mode") or "full_cli")
        role = str(data["role"])
        raw_tiers = data.get("tiers")
        tiers = (
            [str(item) for item in raw_tiers]
            if isinstance(raw_tiers, list) and raw_tiers
            else [str(data["tier"])]
        )
        stored_bindings = data.get("bindings")
        validated_bindings: dict[str, dict[str, str]] = {}
        for tier in tiers:
            binding, issue = _governed_proposal_binding(
                project_root,
                role_key=role,
                cli_agent=str(data.get("cli_agent") or ""),
                model_key=str(data.get("model") or ""),
                tier=tier,
            )
            expected = (
                (stored_bindings or {}).get(tier)
                if isinstance(stored_bindings, dict)
                else {
                    "invocation_contract": data.get("invocation_contract"),
                    "capacity_route": data.get("capacity_route"),
                }
            )
            if issue or binding is None or expected != binding:
                console.print(
                    f"[red]Proposal no longer matches governed routing for {tier}: "
                    f"{issue or 'contract/capacity route mismatch'}[/red]"
                )
                raise typer.Exit(code=1)
            validated_bindings[tier] = binding
        expected_before = data.get("profiles_sha256_before")
        expected_after = data.get("profiles_sha256_after")
        if proposal_status == "applying" and current_profiles_sha256 == expected_after:
            data["status"] = "applied"
            data["applied_at"] = datetime.now(timezone.utc).isoformat()
            _write_yaml(path, data)
            console.print(
                yaml.safe_dump(
                    {
                        "status": "applied",
                        "proposal_id": proposal,
                        "role": role,
                        "tiers": tiers,
                        "recovered_from": "applying",
                    },
                    sort_keys=False,
                ).rstrip()
            )
            return
        if expected_before and current_profiles_sha256 != expected_before:
            console.print(
                "[red]Model profiles changed after proposal creation; "
                "create a new proposal[/red]"
            )
            raise typer.Exit(code=1)
        modes = profiles.setdefault("modes", {})
        tier_map = modes.setdefault(mode_name, {}).setdefault("tiers", {})
        old_configs: dict[str, Any] = {}
        new_configs: dict[str, Any] = {}
        for tier in tiers:
            tier_cfg = tier_map.setdefault(tier, {})
            old_cfg = tier_cfg.get(role)
            old_configs[tier] = old_cfg
            if isinstance(old_cfg, dict):
                new_cfg = dict(old_cfg)
            else:
                new_cfg = {"executor_type": "cli_agent"}
            binding = validated_bindings[tier]
            new_cfg.update({
                "executor_type": "cli_agent",
                "cli_agent": data["cli_agent"],
                "default": data["model"],
                "invocation_contract": binding["invocation_contract"],
                "capacity_route": binding["capacity_route"],
            })
            tier_cfg[role] = new_cfg
            new_configs[tier] = new_cfg
        data["status"] = "applying"
        data["old_configs"] = old_configs
        data["new_configs"] = new_configs
        data["profiles_sha256_before"] = current_profiles_sha256
        data["profiles_sha256_after"] = _mapping_sha256(profiles)
        _write_yaml(path, data)
        _write_yaml(profiles_path, profiles)
        data["status"] = "applied"
        data["applied_at"] = datetime.now(timezone.utc).isoformat()
        _write_yaml(path, data)
        console.print(
            yaml.safe_dump(
                {
                    "status": "applied",
                    "proposal_id": proposal,
                    "role": role,
                    "tiers": tiers,
                },
                sort_keys=False,
            ).rstrip()
        )

    @models_app.command("catalog-propose")
    def propose_catalog_model(
        model_key: str = typer.Option(
            ...,
            "--model-key",
            help="Stable model catalog key using lowercase letters, digits, and underscores.",
        ),
        entry_file: Path = typer.Option(
            ...,
            "--entry-file",
            exists=True,
            dir_okay=False,
            readable=True,
            help="YAML mapping containing the complete governed model entry.",
        ),
    ) -> None:
        """Propose a new or updated backend model without mutating the catalog."""
        try:
            entry = yaml.safe_load(entry_file.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            console.print(f"[red]Cannot read model entry: {exc}[/red]")
            raise typer.Exit(code=1) from exc
        issue = _validate_catalog_model_entry(project_root, model_key, entry)
        if issue:
            console.print(f"[red]{issue}[/red]")
            raise typer.Exit(code=1)
        catalog = _read_yaml(
            project_root / "config" / "model_catalog.yml",
            {},
        ) or {}
        old_entry = (catalog.get("models") or {}).get(model_key)
        proposal_id = _proposal_id("catalog", model_key, str(entry["model_id"]))
        proposal = {
            "schema_version": 1,
            "proposal_id": proposal_id,
            "proposal_kind": "catalog_model",
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "target_file": "config/model_catalog.yml",
            "model_key": model_key,
            "entry": entry,
            "entry_sha256": _mapping_sha256(entry),
            "old_entry_sha256": _mapping_sha256(old_entry),
            "requires_agentlab_apply": True,
            "frontdesk_may_apply": False,
        }
        _write_yaml(_proposal_dir(project_root) / f"{proposal_id}.yml", proposal)
        console.print(
            yaml.safe_dump(proposal, sort_keys=False, allow_unicode=True).rstrip()
        )

    @models_app.command("catalog-apply")
    @_serialized_model_config_write(project_root)
    def apply_catalog_model(
        proposal: str = typer.Option(
            ...,
            "--proposal",
            help="Proposal id from models catalog-propose.",
        ),
    ) -> None:
        """Apply one audited catalog model proposal after drift validation."""
        path = _proposal_dir(project_root) / f"{proposal}.yml"
        data = _read_yaml(path, {}) or {}
        if (
            data.get("proposal_id") != proposal
            or data.get("proposal_kind") != "catalog_model"
        ):
            console.print(f"[red]Unknown catalog proposal id: {proposal}[/red]")
            raise typer.Exit(code=1)
        proposal_status = str(data.get("status") or "")
        if proposal_status not in {"pending", "applying"}:
            console.print(f"[red]Proposal is not pending/applying: {proposal}[/red]")
            raise typer.Exit(code=1)
        model_key = str(data.get("model_key") or "")
        entry = data.get("entry")
        issue = _validate_catalog_model_entry(project_root, model_key, entry)
        if issue or _mapping_sha256(entry) != data.get("entry_sha256"):
            console.print(
                f"[red]Catalog proposal validation failed: "
                f"{issue or 'entry hash mismatch'}[/red]"
            )
            raise typer.Exit(code=1)
        catalog_path = project_root / "config" / "model_catalog.yml"
        catalog = _read_yaml(catalog_path, {}) or {}
        models = catalog.setdefault("models", {})
        current_entry = models.get(model_key)
        current_entry_sha256 = _mapping_sha256(current_entry)
        if (
            proposal_status == "applying"
            and current_entry_sha256 == data.get("entry_sha256")
        ):
            data["status"] = "applied"
            data["applied_at"] = datetime.now(timezone.utc).isoformat()
            _write_yaml(path, data)
            console.print(
                yaml.safe_dump(
                    {
                        "status": "applied",
                        "proposal_id": proposal,
                        "model_key": model_key,
                        "entry_sha256": data["entry_sha256"],
                        "recovered_from": "applying",
                    },
                    sort_keys=False,
                ).rstrip()
            )
            return
        if current_entry_sha256 != data.get("old_entry_sha256"):
            console.print(
                "[red]Catalog changed after proposal creation; create a new proposal[/red]"
            )
            raise typer.Exit(code=1)
        models[model_key] = entry
        data["status"] = "applying"
        _write_yaml(path, data)
        _write_yaml(catalog_path, catalog)
        data["status"] = "applied"
        data["applied_at"] = datetime.now(timezone.utc).isoformat()
        _write_yaml(path, data)
        console.print(
            yaml.safe_dump(
                {
                    "status": "applied",
                    "proposal_id": proposal,
                    "model_key": model_key,
                    "entry_sha256": data["entry_sha256"],
                },
                sort_keys=False,
            ).rstrip()
        )

    @models_app.command("capacity")
    def show_capacity(
        run_dir: Path | None = typer.Option(
            None,
            "--run-dir",
            help="Optional run directory containing model_capacity_ledger.yml.",
        ),
        probe: str | None = typer.Option(
            None,
            "--probe",
            help=(
                "Run one pool probe or 'all'. Probes only report declared "
                "catalog/auth facts; quota values remain evidence-or-null."
            ),
        ),
    ) -> None:
        """Show honest capacity state; unknown remaining/reset values stay null."""
        policy = _read_yaml(project_root / "config" / "model_capacity.yml", {}) or {}
        ledger_name = str(
            (policy.get("ledger") or {}).get("filename")
            or "model_capacity_ledger.yml"
        )
        ledger_path = (run_dir / ledger_name) if run_dir else None
        probe_results: list[dict[str, Any]] = []
        probe_scope = None
        if probe:
            if run_dir is None:
                raise typer.BadParameter("--probe requires --run-dir for its audit ledger")
            import subprocess

            try:
                from agent_runtime.model_capacity import ModelCapacity
            except ModuleNotFoundError:  # pragma: no cover - direct script path
                from model_capacity import ModelCapacity

            capacity = ModelCapacity(policy, ledger_path)

            def runner(command: tuple[str, ...]):
                try:
                    return subprocess.run(
                        list(command),
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=30,
                    )
                except FileNotFoundError:
                    return {
                        "returncode": 127,
                        "stdout": "",
                        "stderr": f"probe executable not found: {command[0]}",
                    }
                except subprocess.TimeoutExpired:
                    return {
                        "returncode": 124,
                        "stdout": "",
                        "stderr": f"safe probe timed out: {' '.join(command)}",
                    }

            if probe == "all":
                pool_ids = [
                    str(pool_id)
                    for pool_id, pool in sorted((policy.get("pools") or {}).items())
                    if isinstance(pool, dict) and pool.get("probe") is not None
                ]
                probe_scope = "all_declared_safe_probes"
            else:
                pool_ids = [probe]
                probe_scope = "single_pool"
            observed_at = datetime.now(timezone.utc).isoformat()
            for pool_id in pool_ids:
                result = capacity.probe(
                    pool_id,
                    runner=runner,
                    attempt_id=f"models-capacity:{pool_id}:{observed_at}",
                )
                result["probe_capability"] = (
                    ((policy.get("pools") or {}).get(pool_id) or {}).get(
                        "probe_capability"
                    )
                )
                probe_results.append(result)

        payload = {
            "status": "observed",
            "ledger_path": str(ledger_path) if ledger_path else None,
            "remaining_and_reset_policy": "provider_evidence_or_null",
            "pools": _capacity_rows(project_root, ledger_path),
            "probe_scope": probe_scope,
            "probe_result": probe_results[0] if len(probe_results) == 1 else None,
            "probe_results": probe_results,
        }
        console.print(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).rstrip()
        )

    @models_app.command("doctor")
    def doctor_models() -> None:
        """Audit model routing policy and high-cost defaults."""
        from model_resolver import validate_model_configuration
        from config_loader import load_agentlab_configs

        check = validate_model_configuration(load_agentlab_configs(project_root))
        issues = list(check.get("issues") or []) + _doctor_issues(project_root)
        status = "fail" if any(item.get("severity") == "error" for item in issues) else "pass"
        console.print(yaml.safe_dump({"status": status, "issue_count": len(issues), "issues": issues}, sort_keys=False, allow_unicode=True).rstrip())
        if status != "pass":
            raise typer.Exit(code=1)

    app.add_typer(models_app, name="models")
