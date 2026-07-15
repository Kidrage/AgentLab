"""User-facing model configuration commands."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import re
import shlex

import typer
import yaml
from rich.console import Console
from rich.table import Table


MODE_TO_TIER = {
    "quality": "full",
    "balanced": "performance",
    "frugal": "low",
    "full": "full",
    "performance": "performance",
    "low": "low",
}

ROLE_ALIASES = {
    "supervisor": "supervisor",
    "reposcout": "reposcout",
    "repo_scout": "reposcout",
    "researcher": "researcher",
    "observer": "observer",
    "interfacemapper": "interface_mapper",
    "interface_mapper": "interface_mapper",
    "promptengineer": "prompt_engineer",
    "prompt_engineer": "prompt_engineer",
    "coder": "coder",
    "artifactproducer": "artifact_producer",
    "artifact_producer": "artifact_producer",
    "reviewer": "reviewer",
    "scribe": "scribe",
    "testerauditor": "tester_auditor",
    "tester_auditor": "tester_auditor",
    "verifier": "verifier",
    "archivist": "archivist",
    "writer": "writer",
    "visual_reviewer": "visual_reviewer",
    "narrativeplanner": "narrative_planner",
    "narrative_planner": "narrative_planner",
}


CAPACITY_ROLE_ALIASES = {"visual_reviewer": "reviewer"}
ROLE_KEY_TO_CANONICAL = {
    "supervisor": "Supervisor",
    "reposcout": "RepoScout",
    "researcher": "Researcher",
    "observer": "Observer",
    "interface_mapper": "InterfaceMapper",
    "prompt_engineer": "PromptEngineer",
    "coder": "Coder",
    "artifact_producer": "ArtifactProducer",
    "writer": "Writer",
    "reviewer": "Reviewer",
    "visual_reviewer": "Reviewer",
    "scribe": "Scribe",
    "tester_auditor": "TesterAuditor",
    "verifier": "Verifier",
    "archivist": "Archivist",
    "narrative_planner": "NarrativePlanner",
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _role_key(role: str) -> str:
    key = str(role or "").replace("-", "_").replace(" ", "_").lower()
    return ROLE_ALIASES.get(key, key)


def _proposal_dir(root: Path) -> Path:
    return root / ".agentlab" / "model_proposals"


def _proposal_id(role: str, cli: str, model: str) -> str:
    seed = f"{datetime.now(timezone.utc).isoformat()}:{role}:{cli}:{model}".encode()
    return "model_" + hashlib.sha1(seed).hexdigest()[:12]


def _dynamic_full_cli_enabled(root: Path) -> bool:
    profiles = _read_yaml(root / "config" / "agent_model_profiles.yml", {}) or {}
    runtime = profiles.get("dynamic_runtime") or {}
    default_mode = str(profiles.get("default_mode") or "full_cli")
    enabled_modes = {str(item) for item in runtime.get("enabled_modes") or ["full_cli"]}
    return bool(runtime.get("enabled")) and default_mode in enabled_modes


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
        raise typer.BadParameter("mode must be quality, balanced, frugal, full, performance, or low")
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
    if billing == "codex_oauth":
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
            }
        )
    return rows


def _role_rows(root: Path, *, mode: str, role: str | None) -> list[dict[str, str]]:
    registry_path = root / "config" / "runtime_registry.yml"
    if registry_path.exists():
        try:
            from agent_runtime.routing.dynamic_selector import DynamicRouteSelector
            from agent_runtime.runtime_registry import RuntimeRegistry
        except ModuleNotFoundError:  # pragma: no cover - direct script path
            from routing.dynamic_selector import DynamicRouteSelector
            from runtime_registry import RuntimeRegistry

        registry = RuntimeRegistry.load(root)
        if not registry.validate():
            selector = DynamicRouteSelector(registry)
            selected_role = _role_key(role) if role else None
            rows: list[dict[str, str]] = []
            for role_key in sorted((registry.data.get("role_routes") or {})):
                if selected_role and role_key != selected_role:
                    continue
                decision = selector.select(
                    registry.task_demand(role_key, preset=_tier(mode))
                )
                if decision.get("status") != "selected":
                    rows.append({
                        "role": role_key,
                        "cli": "blocked",
                        "model": "",
                        "provider": "",
                        "cost": "unknown",
                        "pool": "",
                        "fallback": "",
                        "fit": str(decision.get("reason") or "no eligible route"),
                        "risk": ",".join(
                            str(item.get("reason") or "")
                            for item in decision.get("rejected_routes") or []
                        ),
                        "route": "",
                        "channel": "",
                    })
                    continue
                route_id = str(decision["route_id"])
                identity = registry.route_identity(route_id)
                shell = registry.shells.get(identity.shell_id) or {}
                quote = decision.get("cost") or {}
                cost_value = quote.get("cny_amount")
                billing = str(quote.get("billing_mode") or "unknown")
                cost = (
                    f"CNY {float(cost_value):.6f} ({billing})"
                    if cost_value is not None
                    else f"unknown ({billing})"
                )
                fallback_ids = [
                    item
                    for item in registry.candidates_for(role_key)
                    if item != route_id
                    and str((registry.routes.get(item) or {}).get("status") or "active")
                    == "active"
                ]
                rows.append({
                    "role": role_key,
                    "cli": f"{identity.shell_id}/{shell.get('worker_id') or identity.shell_id}",
                    "model": identity.model_id,
                    "provider": identity.provider_id,
                    "cost": cost,
                    "pool": identity.credential_pool_id,
                    "fallback": ",".join(fallback_ids),
                    "fit": f"quality={decision.get('quality')} floor={decision.get('quality_floor')}",
                    "risk": ",".join(
                        f"{item.get('route_id')}:{item.get('reason')}"
                        for item in decision.get("rejected_routes") or []
                    )[:160],
                    "route": route_id,
                    "channel": str(shell.get("preferred_channel") or "cli"),
                })
            return rows

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
            "route": capacity_route_id,
            "channel": "legacy",
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
    table.add_column("Route", overflow="fold")
    table.add_column("Channel", overflow="fold")
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
            row.get("route", ""),
            row.get("channel", ""),
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
                    f"route={row.get('route', '')}",
                    f"channel={row.get('channel', '')}",
                ]
            )
        )


def _runtime_quota_snapshots(
    registry: Any,
    ledger_path: Path | None,
) -> dict[str, dict[str, Any]]:
    try:
        from agent_runtime.runtime_registry import load_runtime_quota_snapshots
    except ModuleNotFoundError:  # pragma: no cover - direct script path
        from runtime_registry import load_runtime_quota_snapshots

    return load_runtime_quota_snapshots(registry, ledger_path)


def _runtime_matrix_rows(root: Path, role: str | None = None) -> list[dict[str, str]]:
    try:
        from agent_runtime.runtime_registry import RuntimeRegistry, canonical_role
    except ModuleNotFoundError:  # pragma: no cover - direct script path
        from runtime_registry import RuntimeRegistry, canonical_role

    registry = RuntimeRegistry.load(root)
    wanted = canonical_role(role) if role else None
    rows: list[dict[str, str]] = []
    for route_id, route in sorted(registry.routes.items()):
        identity = registry.route_identity(route_id)
        if wanted and canonical_role(identity.role) != wanted:
            continue
        shell = registry.shells.get(identity.shell_id) or {}
        model = registry.models.get(identity.model_id) or {}
        provider = registry.providers.get(identity.provider_id) or {}
        rows.append({
            "role": identity.role,
            "route": route_id,
            "status": str(route.get("status") or "active"),
            "shell": identity.shell_id,
            "worker": str(shell.get("worker_id") or identity.shell_id),
            "channel": str(shell.get("preferred_channel") or "cli"),
            "adapter": identity.adapter_id,
            "profile": identity.profile_ref or "",
            "provider": identity.provider_id,
            "model": identity.model_id,
            "provider_model": str(model.get("provider_model_id") or ""),
            "pool": identity.credential_pool_id,
            "billing": str(provider.get("billing_mode") or ""),
        })
    return rows


def _render_runtime_matrix(console: Console, rows: list[dict[str, str]]) -> None:
    table = Table()
    for label in (
        "Role",
        "Route",
        "Status",
        "Shell/worker",
        "Channel",
        "Adapter",
        "Profile",
        "Provider",
        "Model",
        "Provider model",
        "Pool",
        "Billing",
    ):
        table.add_column(label, overflow="fold")
    for row in rows:
        table.add_row(
            row["role"],
            row["route"],
            row["status"],
            f"{row['shell']}/{row['worker']}",
            row["channel"],
            row["adapter"],
            row["profile"],
            row["provider"],
            row["model"],
            row["provider_model"],
            row["pool"],
            row["billing"],
        )
    console.print(table)
    for row in rows:
        console.print(" | ".join(f"{key}={value}" for key, value in row.items()))


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
    runtime_registry_path = root / "config" / "runtime_registry.yml"
    if runtime_registry_path.exists():
        try:
            from agent_runtime.runtime_registry import RuntimeRegistry
        except ModuleNotFoundError:  # pragma: no cover - direct script path
            from runtime_registry import RuntimeRegistry
        for runtime_issue in RuntimeRegistry.load(root).validate():
            issues.append({
                "severity": str(runtime_issue.get("severity") or "error"),
                "scope": str(runtime_issue.get("scope") or "runtime_registry"),
                "issue": "runtime_registry:"
                + str(runtime_issue.get("issue") or "invalid"),
                "value": "",
            })

    try:
        from agent_runtime.shell_governance import validate_production_argv
    except ModuleNotFoundError:  # pragma: no cover - direct script path
        from shell_governance import validate_production_argv
    for contract_id, contract in (
        (invocation_contracts.get("contracts") or {}).items()
    ):
        template = str((contract or {}).get("template") or "")
        if not template:
            continue
        try:
            argv = shlex.split(template)
        except ValueError as exc:
            issues.append({
                "severity": "error",
                "scope": f"worker_invocation_contracts.contracts.{contract_id}.template",
                "issue": "invalid_shell_template",
                "value": str(exc),
            })
            continue
        shell_issues = validate_production_argv(argv)
        if shell_issues:
            issues.append({
                "severity": "error",
                "scope": f"worker_invocation_contracts.contracts.{contract_id}.template",
                "issue": "production_shell_bypass_forbidden",
                "value": ",".join(shell_issues),
            })
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
            if not _numeric_paths(
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
        mode: str = typer.Option("balanced", "--mode", help="quality, balanced, or frugal."),
    ) -> None:
        """Show role model routing with cost source and risks."""
        rows = _role_rows(project_root, mode=mode, role=role)
        _render_rows(console, rows)
        if role and not rows:
            raise typer.Exit(code=1)

    @models_app.command("matrix")
    def model_matrix(
        role: str | None = typer.Option(
            None,
            "--role",
            help="Limit output to one normalized runtime role.",
        ),
    ) -> None:
        """Show every normalized shell/adapter/provider/model route."""
        rows = _runtime_matrix_rows(project_root, role)
        _render_runtime_matrix(console, rows)
        if role and not rows:
            raise typer.Exit(code=1)

    @models_app.command("route-explain")
    def explain_route(
        role: str = typer.Option(..., "--role", help="Role to route, e.g. Writer."),
        mode: str = typer.Option(
            "balanced",
            "--mode",
            help="quality, balanced, frugal, full, performance, or low.",
        ),
        modalities: str = typer.Option(
            "",
            "--modalities",
            help="Comma-separated required input modalities.",
        ),
        data_class: str = typer.Option("private", "--data-class"),
        input_tokens: int = typer.Option(0, "--input-tokens", min=0),
        output_tokens: int = typer.Option(0, "--output-tokens", min=0),
        predicted_quota_percent: float = typer.Option(
            0.0,
            "--predicted-quota-percent",
            min=0.0,
        ),
        risk_reserve_percent: float = typer.Option(
            0.0,
            "--risk-reserve-percent",
            min=0.0,
        ),
        long_batch: bool = typer.Option(False, "--long-batch"),
        checkpoint_complete: bool = typer.Option(
            True,
            "--checkpoint-complete/--mid-task",
        ),
        quota_ledger: Path | None = typer.Option(
            None,
            "--quota-ledger",
            help="Optional model_capacity_ledger.yml with observed quota only.",
        ),
    ) -> None:
        """Explain hard filters, quality floor, and effective-cost selection."""
        try:
            from agent_runtime.routing.dynamic_selector import DynamicRouteSelector
            from agent_runtime.runtime_registry import (
                RuntimeRegistry,
                load_runtime_route_states,
            )
        except ModuleNotFoundError:  # pragma: no cover - direct script path
            from routing.dynamic_selector import DynamicRouteSelector
            from runtime_registry import RuntimeRegistry, load_runtime_route_states

        registry = RuntimeRegistry.load(project_root)
        issues = registry.validate()
        if issues:
            console.print(
                yaml.safe_dump(
                    {"status": "invalid_registry", "issues": issues},
                    sort_keys=False,
                    allow_unicode=True,
                ).rstrip(),
                markup=False,
                soft_wrap=True,
            )
            raise typer.Exit(code=1)
        required = [
            item.strip().lower()
            for item in modalities.split(",")
            if item.strip()
        ]
        demand = registry.task_demand(
            _role_key(role),
            preset=_tier(mode),
            required_modalities=required,
            data_class=data_class,
            predicted_input_tokens=input_tokens,
            predicted_output_tokens=output_tokens,
            predicted_quota_percent=predicted_quota_percent,
            risk_reserve_percent=risk_reserve_percent,
            long_batch=long_batch,
            checkpoint_complete=checkpoint_complete,
        )
        decision = DynamicRouteSelector(
            registry,
            quota_snapshots=_runtime_quota_snapshots(registry, quota_ledger),
            route_states=load_runtime_route_states(registry, quota_ledger),
        ).select(demand)
        decision["demand"] = {
            "mode": mode,
            "preset": _tier(mode),
            "modalities": required,
            "data_class": data_class,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "predicted_quota_percent": predicted_quota_percent,
            "risk_reserve_percent": risk_reserve_percent,
            "long_batch": long_batch,
            "checkpoint_complete": checkpoint_complete,
        }
        console.print(
            yaml.safe_dump(decision, sort_keys=False, allow_unicode=True).rstrip(),
            markup=False,
            soft_wrap=True,
        )
        if decision.get("status") != "selected":
            raise typer.Exit(code=1)

    @models_app.command("plan")
    def plan_models(
        mode: str = typer.Option(..., "--mode", help="quality, balanced, or frugal."),
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
        mode: str = typer.Option("balanced", "--mode", help="quality, balanced, or frugal."),
    ) -> None:
        """Create a model-routing proposal without changing config."""
        catalog = _read_yaml(project_root / "config" / "model_catalog.yml", {}) or {}
        if model not in (catalog.get("models") or {}):
            console.print(f"[red]Unknown model catalog key: {model}[/red]")
            raise typer.Exit(code=1)
        role_key = _role_key(role)
        tier = _tier(mode)
        binding, issue = _governed_proposal_binding(
            project_root,
            role_key=role_key,
            cli_agent=cli,
            model_key=model,
            tier=tier,
        )
        if issue or binding is None:
            console.print(f"[red]{issue or 'Invalid governed model route'}[/red]")
            raise typer.Exit(code=1)
        if _dynamic_full_cli_enabled(project_root):
            console.print(
                "[red]Fixed-model proposals cannot mutate the generated full_cli "
                "compatibility view. Submit a reviewed runtime_registry route change "
                "and validate it with models route-explain.[/red]"
            )
            raise typer.Exit(code=1)
        proposal_id = _proposal_id(role, cli, model)
        proposal = {
            "schema_version": 1,
            "proposal_id": proposal_id,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "target_file": "config/agent_model_profiles.yml",
            "mode": mode,
            "tier": tier,
            "role": role_key,
            "cli_agent": cli,
            "model": model,
            "invocation_contract": binding["invocation_contract"],
            "capacity_route": binding["capacity_route"],
            "requires_agentlab_apply": True,
            "frontdesk_may_apply": False,
        }
        _write_yaml(_proposal_dir(project_root) / f"{proposal_id}.yml", proposal)
        console.print(yaml.safe_dump(proposal, sort_keys=False, allow_unicode=True).rstrip())

    @models_app.command("apply")
    def apply_model_proposal(
        proposal: str = typer.Option(..., "--proposal", help="Proposal id from models propose."),
    ) -> None:
        """Apply an explicit pending model proposal."""
        path = _proposal_dir(project_root) / f"{proposal}.yml"
        data = _read_yaml(path, {}) or {}
        if not data or data.get("proposal_id") != proposal:
            console.print(f"[red]Unknown proposal id: {proposal}[/red]")
            raise typer.Exit(code=1)
        if data.get("status") != "pending":
            console.print(f"[red]Proposal is not pending: {proposal}[/red]")
            raise typer.Exit(code=1)
        if _dynamic_full_cli_enabled(project_root):
            console.print(
                "[red]Refusing to apply a fixed-model proposal to dynamic full_cli; "
                "config/agent_model_profiles.yml is a generated compatibility view.[/red]"
            )
            raise typer.Exit(code=1)
        profiles_path = project_root / "config" / "agent_model_profiles.yml"
        profiles = _read_yaml(profiles_path, {}) or {}
        mode_name = str(profiles.get("default_mode") or "full_cli")
        role = str(data["role"])
        tier = str(data["tier"])
        binding, issue = _governed_proposal_binding(
            project_root,
            role_key=role,
            cli_agent=str(data.get("cli_agent") or ""),
            model_key=str(data.get("model") or ""),
            tier=tier,
        )
        if (
            issue
            or binding is None
            or data.get("invocation_contract") != binding["invocation_contract"]
            or data.get("capacity_route") != binding["capacity_route"]
        ):
            console.print(
                f"[red]Proposal no longer matches governed routing: "
                f"{issue or 'contract/capacity route mismatch'}[/red]"
            )
            raise typer.Exit(code=1)
        modes = profiles.setdefault("modes", {})
        tier_cfg = modes.setdefault(mode_name, {}).setdefault("tiers", {}).setdefault(tier, {})
        old_cfg = tier_cfg.get(role)
        if isinstance(old_cfg, dict):
            new_cfg = dict(old_cfg)
        else:
            new_cfg = {"executor_type": "cli_agent"}
        new_cfg.update({
            "executor_type": "cli_agent",
            "cli_agent": data["cli_agent"],
            "default": data["model"],
            "invocation_contract": binding["invocation_contract"],
            "capacity_route": binding["capacity_route"],
        })
        tier_cfg[role] = new_cfg
        _write_yaml(profiles_path, profiles)
        data["status"] = "applied"
        data["applied_at"] = datetime.now(timezone.utc).isoformat()
        data["old_config"] = old_cfg
        data["new_config"] = new_cfg
        _write_yaml(path, data)
        console.print(yaml.safe_dump({"status": "applied", "proposal_id": proposal, "role": role}, sort_keys=False).rstrip())

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
            help="Explicitly run one policy-allowlisted non-consuming auth/model probe.",
        ),
    ) -> None:
        """Show honest capacity state; unknown remaining/reset values stay null."""
        policy = _read_yaml(project_root / "config" / "model_capacity.yml", {}) or {}
        ledger_name = str(
            (policy.get("ledger") or {}).get("filename")
            or "model_capacity_ledger.yml"
        )
        ledger_path = (run_dir / ledger_name) if run_dir else None
        probe_result = None
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
                return subprocess.run(
                    list(command),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )

            probe_result = capacity.probe(
                probe,
                runner=runner,
                attempt_id=f"models-capacity:{datetime.now(timezone.utc).isoformat()}",
            )

        payload = {
            "status": "observed",
            "ledger_path": str(ledger_path) if ledger_path else None,
            "remaining_and_reset_policy": "provider_evidence_or_null",
            "pools": _capacity_rows(project_root, ledger_path),
            "probe_result": probe_result,
        }
        console.print(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).rstrip()
        )

    @models_app.command("quota")
    def probe_quota(
        pool: str = typer.Option(
            ...,
            "--pool",
            help="Normalized credential pool or compatibility capacity pool id.",
        ),
        run_dir: Path = typer.Option(
            ...,
            "--run-dir",
            help="Run-local directory that owns model_capacity_ledger.yml.",
        ),
        predicted_quota_percent: float = typer.Option(
            0.0,
            "--predicted-quota-percent",
            min=0.0,
        ),
        risk_reserve_percent: float = typer.Option(
            0.0,
            "--risk-reserve-percent",
            min=0.0,
        ),
    ) -> None:
        """Run one allowlisted /usage probe and persist normalized telemetry."""
        try:
            from agent_runtime.model_capacity import ModelCapacity
            from agent_runtime.quota_probes import run_interactive_probe
            from agent_runtime.runtime_registry import RuntimeRegistry
        except ModuleNotFoundError:  # pragma: no cover - direct script path
            from model_capacity import ModelCapacity
            from quota_probes import run_interactive_probe
            from runtime_registry import RuntimeRegistry

        policy = _read_yaml(project_root / "config" / "model_capacity.yml", {}) or {}
        registry = RuntimeRegistry.load(project_root)
        capacity_pool = pool
        runtime_pool = registry.credential_pools.get(pool)
        if isinstance(runtime_pool, dict):
            capacity_pool = str(
                runtime_pool.get("legacy_capacity_pool_id") or pool
            )
        if capacity_pool not in (policy.get("pools") or {}):
            raise typer.BadParameter(f"unknown quota pool: {pool}")
        run_dir.mkdir(parents=True, exist_ok=True)
        ledger_name = str(
            (policy.get("ledger") or {}).get("filename")
            or "model_capacity_ledger.yml"
        )
        capacity = ModelCapacity(policy, run_dir / ledger_name)
        result = capacity.probe_quota(
            capacity_pool,
            runner=run_interactive_probe,
            attempt_id=f"models-quota:{datetime.now(timezone.utc).isoformat()}",
            predicted_unit_usage_percent=predicted_quota_percent,
            risk_reserve_percent=risk_reserve_percent,
        )
        payload = {
            "requested_pool_id": pool,
            "capacity_pool_id": capacity_pool,
            "ledger_path": str(run_dir / ledger_name),
            **result,
        }
        console.print(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).rstrip(),
            markup=False,
            soft_wrap=True,
        )

    @models_app.command("receipt")
    def show_receipts(
        run_dir: Path = typer.Option(
            ...,
            "--run-dir",
            help="Run directory containing usage_receipt_<role>.yml files.",
        ),
    ) -> None:
        """Summarize immutable route, usage, pricing, and quota receipts."""
        receipts: list[dict[str, Any]] = []
        for path in sorted(run_dir.glob("usage_receipt_*.yml")):
            payload = _read_yaml(path, {}) or {}
            receipt = payload.get("usage_receipt")
            if not isinstance(receipt, dict):
                continue
            receipts.append({"path": str(path), **receipt})
        known_costs = [
            float(item["cost_cny"])
            for item in receipts
            if item.get("cost_cny") is not None
        ]
        payload = {
            "status": "observed",
            "run_dir": str(run_dir),
            "receipt_count": len(receipts),
            "known_cost_cny": round(sum(known_costs), 8),
            "unavailable_cost_count": sum(
                1 for item in receipts if item.get("cost_cny") is None
            ),
            "receipts": receipts,
        }
        console.print(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).rstrip(),
            markup=False,
            soft_wrap=True,
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
