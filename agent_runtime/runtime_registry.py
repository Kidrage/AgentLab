"""Normalized runtime registry and compatibility compiler.

The registry names the complete execution identity of a model route.  It is a
configuration authority, not a credential store: profile references may point
at user-managed shell state, but secrets are never loaded or copied here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Mapping

import yaml


ALLOWED_BILLING_MODES = {
    "api_metered",
    "api_free_tier",
    "oauth_subscription",
    "shell_only",
}
ALLOWED_ROUTE_STATUS = {"active", "disabled", "quarantined"}
ALLOWED_ADAPTER_PROTOCOLS = {
    "hermes_runs",
    "hermes_cli",
    "claude_cli",
    "agy_cli",
    "qwen_cli",
    "grok_cli",
    "openai_chat",
    "openai_responses",
    "anthropic_messages",
    "gemini_generate_content",
}
SECRET_KEY_RE = re.compile(r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret)$", re.I)


def canonical_role(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def utc_timestamp(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class RouteIdentity:
    role: str
    shell_id: str
    adapter_id: str
    profile_ref: str | None
    provider_id: str
    model_id: str
    credential_pool_id: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RouteIdentity":
        return cls(
            role=str(value.get("role") or ""),
            shell_id=str(value.get("shell_id") or ""),
            adapter_id=str(value.get("adapter_id") or ""),
            profile_ref=str(value["profile_ref"]) if value.get("profile_ref") else None,
            provider_id=str(value.get("provider_id") or ""),
            model_id=str(value.get("model_id") or ""),
            credential_pool_id=str(value.get("credential_pool_id") or ""),
        )


@dataclass(frozen=True, slots=True)
class TaskDemand:
    role: str
    capability_weights: dict[str, float]
    required_modalities: tuple[str, ...] = ()
    quality_floor: float = 0.78
    data_class: str = "private"
    predicted_input_tokens: int = 0
    predicted_output_tokens: int = 0
    predicted_quota_percent: float = 0.0
    risk_reserve_percent: float = 0.0
    long_batch: bool = False
    checkpoint_complete: bool = True
    allowed_provider_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class QuotaWindow:
    name: str
    remaining_percent: float | None
    reset_at: str | None
    confidence: str = "unknown"


@dataclass(frozen=True, slots=True)
class QuotaSnapshot:
    credential_pool_id: str
    status: str
    observed_at: str
    stale_at: str
    remaining_percent: float | None = None
    reset_at: str | None = None
    source_kind: str = "cli_usage"
    confidence: str = "unknown"
    windows: tuple[QuotaWindow, ...] = ()
    failure_class: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["windows"] = [asdict(item) for item in self.windows]
        return payload


@dataclass(frozen=True, slots=True)
class UsageReceipt:
    route_id: str
    identity: RouteIdentity
    started_at: str
    completed_at: str
    input_tokens: int | None
    output_tokens: int | None
    native_cost: float | None
    native_currency: str | None
    cost_cny: float | None
    billing_mode: str
    pricing_version: str | None
    fx_version: str | None
    quota_before_percent: float | None = None
    quota_after_percent: float | None = None
    checkpoint_id: str | None = None
    fallback_from: str | None = None
    execution_status: str = "completed"
    usage_source: str | None = None
    exact_usage_available: bool | None = None
    cost_exact: bool | None = None
    execution_channel: str | None = None
    attempt_id: str | None = None
    cash_basis: str | None = None
    pricing_source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["identity"] = asdict(self.identity)
        return {"usage_receipt": data}

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return path


@dataclass(slots=True)
class RuntimeRegistry:
    root: Path
    data: dict[str, Any]
    routing_policy: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(
        cls,
        root: Path,
        *,
        registry_path: str = "config/runtime_registry.yml",
        routing_policy_path: str = "config/routing_policy.yml",
    ) -> "RuntimeRegistry":
        root = Path(root).resolve()
        return cls(
            root=root,
            data=_read_yaml(root / registry_path),
            routing_policy=_read_yaml(root / routing_policy_path),
        )

    @property
    def routes(self) -> dict[str, Any]:
        value = self.data.get("routes") or {}
        return value if isinstance(value, dict) else {}

    @property
    def models(self) -> dict[str, Any]:
        value = self.data.get("models") or {}
        return value if isinstance(value, dict) else {}

    @property
    def shells(self) -> dict[str, Any]:
        value = self.data.get("shells") or {}
        return value if isinstance(value, dict) else {}

    @property
    def adapters(self) -> dict[str, Any]:
        value = self.data.get("adapters") or {}
        return value if isinstance(value, dict) else {}

    @property
    def providers(self) -> dict[str, Any]:
        value = self.data.get("providers") or {}
        return value if isinstance(value, dict) else {}

    @property
    def credential_pools(self) -> dict[str, Any]:
        value = self.data.get("credential_pools") or {}
        return value if isinstance(value, dict) else {}

    def route_identity(self, route_id: str) -> RouteIdentity:
        route = self.routes.get(route_id)
        if not isinstance(route, Mapping):
            raise KeyError(f"unknown runtime route: {route_id}")
        return RouteIdentity.from_mapping(route.get("identity") or {})

    def candidates_for(self, role: str) -> list[str]:
        role_routes = self.data.get("role_routes") or {}
        wanted = canonical_role(role)
        for configured_role, route_ids in role_routes.items():
            if canonical_role(configured_role) == wanted and isinstance(route_ids, list):
                return [str(item) for item in route_ids]
        return []

    def task_demand(
        self,
        role: str,
        *,
        preset: str = "performance",
        required_modalities: list[str] | tuple[str, ...] | None = None,
        data_class: str | None = None,
        predicted_input_tokens: int = 0,
        predicted_output_tokens: int = 0,
        predicted_quota_percent: float = 0.0,
        risk_reserve_percent: float = 0.0,
        long_batch: bool = False,
        checkpoint_complete: bool = True,
        allowed_provider_ids: list[str] | tuple[str, ...] | None = None,
    ) -> TaskDemand:
        runtime = self.routing_policy.get("runtime_routing") or {}
        presets = runtime.get("presets") or {}
        preset_cfg = presets.get(preset) or presets.get("performance") or {}
        demands = runtime.get("role_demands") or {}
        role_cfg: Mapping[str, Any] = {}
        for configured_role, candidate in demands.items():
            if canonical_role(configured_role) == canonical_role(role) and isinstance(candidate, Mapping):
                role_cfg = candidate
                break
        weights = {
            str(name): float(weight)
            for name, weight in (role_cfg.get("capability_weights") or {}).items()
            if float(weight) > 0
        }
        if not weights:
            weights = {"reasoning": 1.0}
        floor = float(role_cfg.get("quality_floor") or preset_cfg.get("quality_floor") or 0.78)
        if predicted_input_tokens <= 0 and predicted_output_tokens <= 0:
            token_defaults = (
                ((runtime.get("task_demand_defaults") or {}).get("tokens_by_project_size") or {}).get("L2")
                or {}
            )
            predicted_input_tokens = int(token_defaults.get("input") or 0)
            predicted_output_tokens = int(token_defaults.get("output") or 0)
        privacy = runtime.get("privacy") or {}
        return TaskDemand(
            role=role,
            capability_weights=weights,
            required_modalities=tuple(str(item).lower() for item in (required_modalities or role_cfg.get("required_modalities") or [])),
            quality_floor=floor,
            data_class=str(data_class or privacy.get("default_data_class") or "private"),
            predicted_input_tokens=max(0, int(predicted_input_tokens)),
            predicted_output_tokens=max(0, int(predicted_output_tokens)),
            predicted_quota_percent=max(0.0, float(predicted_quota_percent)),
            risk_reserve_percent=max(0.0, float(risk_reserve_percent)),
            long_batch=bool(long_batch),
            checkpoint_complete=bool(checkpoint_complete),
            allowed_provider_ids=tuple(str(item) for item in (allowed_provider_ids or [])),
        )

    def compile_legacy_profile(
        self,
        route_id: str,
        *,
        resolved_mode: str,
        resolved_tier: str,
        decision: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        route = self.routes[route_id]
        identity = self.route_identity(route_id)
        shell = self.shells.get(identity.shell_id) or {}
        profile = {
            "executor_type": str(route.get("executor_type") or "cli_agent"),
            "cli_agent": str(route.get("legacy_cli_agent") or shell.get("worker_id") or identity.shell_id),
            "cli_command": "",
            "default": identity.model_id,
            "invocation_contract": route.get("invocation_contract"),
            "external_ide_allowed": bool(route.get("external_ide_allowed", False)),
            "resolved_mode": resolved_mode,
            "resolved_tier": resolved_tier,
            "resolved_schema": "dynamic_runtime_v1",
            "runtime_route_id": route_id,
            "runtime_identity": asdict(identity),
            "provider": identity.provider_id,
            "adapter_id": identity.adapter_id,
            "profile_ref": identity.profile_ref,
            "execution_channel": shell.get("preferred_channel"),
            "runtime_channel_config": dict(shell.get("channel_config") or {}),
        }
        if decision:
            profile["route_decision"] = dict(decision)
        return profile

    def validate(self) -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []

        def issue(scope: str, message: str) -> None:
            issues.append({"severity": "error", "scope": scope, "issue": message})

        if self.data.get("schema_version") != 1:
            issue("runtime_registry.schema_version", "unsupported_schema_version")
        for section in ("shells", "adapters", "providers", "models", "credential_pools", "routes", "role_routes"):
            if not isinstance(self.data.get(section), dict) or not self.data.get(section):
                issue(f"runtime_registry.{section}", "missing_or_empty_section")

        for adapter_id, adapter in self.adapters.items():
            protocol = str((adapter or {}).get("protocol") or "")
            if protocol not in ALLOWED_ADAPTER_PROTOCOLS:
                issue(f"runtime_registry.adapters.{adapter_id}", "unsupported_adapter_protocol")

        for pool_id, pool in self.credential_pools.items():
            billing = str((pool or {}).get("billing_mode") or "")
            if billing not in ALLOWED_BILLING_MODES:
                issue(f"runtime_registry.credential_pools.{pool_id}", "invalid_billing_mode")

        for route_id, route in self.routes.items():
            if not isinstance(route, Mapping):
                issue(f"runtime_registry.routes.{route_id}", "route_must_be_mapping")
                continue
            if "capacity_route" in route:
                issue(
                    f"runtime_registry.routes.{route_id}.capacity_route",
                    "legacy_capacity_route_forbidden",
                )
            status = str(route.get("status") or "active")
            if status not in ALLOWED_ROUTE_STATUS:
                issue(f"runtime_registry.routes.{route_id}.status", "invalid_route_status")
            identity = RouteIdentity.from_mapping(route.get("identity") or {})
            references = {
                "shell_id": (identity.shell_id, self.shells),
                "adapter_id": (identity.adapter_id, self.adapters),
                "provider_id": (identity.provider_id, self.providers),
                "model_id": (identity.model_id, self.models),
                "credential_pool_id": (identity.credential_pool_id, self.credential_pools),
            }
            if not identity.role:
                issue(f"runtime_registry.routes.{route_id}.identity.role", "missing_role")
            for field_name, (reference, registry) in references.items():
                if not reference or reference not in registry:
                    issue(f"runtime_registry.routes.{route_id}.identity.{field_name}", "unknown_reference")
            model = self.models.get(identity.model_id) or {}
            if model and str(model.get("provider_id") or "") != identity.provider_id:
                issue(f"runtime_registry.routes.{route_id}.identity", "model_provider_mismatch")
            pool = self.credential_pools.get(identity.credential_pool_id) or {}
            if pool and str(pool.get("provider_id") or "") != identity.provider_id:
                issue(f"runtime_registry.routes.{route_id}.identity", "pool_provider_mismatch")

        for role, route_ids in (self.data.get("role_routes") or {}).items():
            if not isinstance(route_ids, list) or not route_ids:
                issue(f"runtime_registry.role_routes.{role}", "route_list_missing")
                continue
            seen: set[str] = set()
            for route_id in route_ids:
                route_id = str(route_id)
                if route_id in seen:
                    issue(f"runtime_registry.role_routes.{role}", "duplicate_route")
                seen.add(route_id)
                route = self.routes.get(route_id)
                if not isinstance(route, Mapping):
                    issue(f"runtime_registry.role_routes.{role}", "unknown_route")
                elif canonical_role((route.get("identity") or {}).get("role")) != canonical_role(role):
                    issue(f"runtime_registry.role_routes.{role}", "cross_role_route")

        def scan_for_secrets(value: Any, path: tuple[str, ...] = ()) -> None:
            if isinstance(value, (list, tuple)):
                for index, nested in enumerate(value):
                    scan_for_secrets(nested, (*path, str(index)))
                return
            if not isinstance(value, Mapping):
                return
            for key, nested in value.items():
                key_text = str(key)
                nested_path = (*path, key_text)
                if SECRET_KEY_RE.search(key_text) and nested not in (None, "", "user_managed"):
                    issue("runtime_registry." + ".".join(nested_path), "inline_secret_forbidden")
                scan_for_secrets(nested, nested_path)

        scan_for_secrets(self.data)
        return issues


def load_runtime_quota_snapshots(
    registry: RuntimeRegistry,
    ledger_path: Path | str | None,
    *,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Load normalized, run-local quota state for runtime credential pools."""

    if not ledger_path:
        return {}
    ledger = _read_yaml(Path(ledger_path))
    states = ledger.get("pools") or {}
    if not isinstance(states, Mapping):
        return {}
    observed_now = now or datetime.now(timezone.utc)
    if observed_now.tzinfo is None:
        observed_now = observed_now.replace(tzinfo=timezone.utc)
    observed_now = observed_now.astimezone(timezone.utc)
    snapshots: dict[str, dict[str, Any]] = {}
    for pool_id, pool in registry.credential_pools.items():
        legacy_id = str((pool or {}).get("legacy_capacity_pool_id") or pool_id)
        raw = states.get(pool_id) or states.get(legacy_id)
        if not isinstance(raw, Mapping):
            continue
        snapshot = dict(raw)
        snapshot["credential_pool_id"] = pool_id
        snapshot["observed_at"] = snapshot.get("observed_at") or snapshot.get(
            "quota_observed_at"
        )
        snapshot["stale_at"] = (
            snapshot.get("stale_at")
            or snapshot.get("quota_stale_at")
            or snapshot.get("expires_at")
        )
        snapshot["windows"] = snapshot.get("windows") or snapshot.get(
            "quota_windows"
        ) or []
        failure_class = str(snapshot.get("failure_class") or "")
        if failure_class == "auth_missing":
            snapshot["status"] = "auth_missing"
        elif failure_class in {"quota_exhausted", "rate_limited"}:
            snapshot["status"] = "quota_reserve"
        elif str(snapshot.get("status") or "") == "closed":
            snapshot["status"] = "available"
        stale_at = _parse_timestamp(snapshot.get("stale_at"))
        if stale_at is not None and observed_now >= stale_at:
            snapshot["status"] = "stale"
        reset_at = _parse_timestamp(snapshot.get("reset_at"))
        if failure_class in {"quota_exhausted", "rate_limited"} and (
            reset_at is None or observed_now >= reset_at
        ):
            snapshot["status"] = "stale"
        snapshots[pool_id] = snapshot
    return snapshots


def load_runtime_route_states(
    registry: RuntimeRegistry,
    ledger_path: Path | str | None,
) -> dict[str, dict[str, Any]]:
    """Load model-scoped dynamic route failures from the run-local ledger."""

    if not ledger_path:
        return {}
    ledger = _read_yaml(Path(ledger_path))
    states = ledger.get("routes") or {}
    if not isinstance(states, Mapping):
        return {}
    direct: dict[str, dict[str, Any]] = {}
    blocked_identities: set[tuple[str, str]] = set()
    for route_id in registry.routes:
        raw = states.get(f"runtime:{route_id}")
        if not isinstance(raw, Mapping):
            continue
        state = dict(raw)
        direct[route_id] = state
        if state.get("status") == "blocked":
            identity = registry.route_identity(route_id)
            blocked_identities.add((identity.model_id, identity.credential_pool_id))
    for route_id in registry.routes:
        identity = registry.route_identity(route_id)
        if (identity.model_id, identity.credential_pool_id) in blocked_identities:
            direct.setdefault(
                route_id,
                {"status": "blocked", "failure_class": "model_unavailable"},
            )
    return direct


def dynamic_runtime_enabled(agent_model_profiles: Mapping[str, Any], mode: str) -> bool:
    config = agent_model_profiles.get("dynamic_runtime") or {}
    enabled_modes = config.get("enabled_modes") or ["full_cli"]
    return bool(config.get("enabled")) and mode in {str(item) for item in enabled_modes}


def resolve_dynamic_profile(
    agent_model_profiles: Mapping[str, Any],
    *,
    agent_role: str,
    resolved_mode: str,
    resolved_tier: str,
    root: Path | None = None,
    routing_context: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not dynamic_runtime_enabled(agent_model_profiles, resolved_mode):
        return None
    config = agent_model_profiles.get("dynamic_runtime") or {}
    agentlab_root = Path(root or Path(__file__).resolve().parent.parent)
    registry = RuntimeRegistry.load(
        agentlab_root,
        registry_path=str(config.get("registry") or "config/runtime_registry.yml"),
        routing_policy_path=str(config.get("routing_policy") or "config/routing_policy.yml"),
    )
    if registry.validate():
        return None
    try:
        from agent_runtime.routing.dynamic_selector import DynamicRouteSelector
    except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
        from routing.dynamic_selector import DynamicRouteSelector
    context = dict(routing_context or {})
    demand = registry.task_demand(
        agent_role,
        preset=resolved_tier,
        required_modalities=context.get("required_modalities"),
        data_class=context.get("data_class"),
        predicted_input_tokens=int(context.get("predicted_input_tokens") or 0),
        predicted_output_tokens=int(context.get("predicted_output_tokens") or 0),
        predicted_quota_percent=float(context.get("predicted_quota_percent") or 0.0),
        risk_reserve_percent=float(context.get("risk_reserve_percent") or 0.0),
        long_batch=bool(context.get("long_batch", False)),
        checkpoint_complete=bool(context.get("checkpoint_complete", True)),
        allowed_provider_ids=context.get("allowed_provider_ids"),
    )
    quota_snapshots = load_runtime_quota_snapshots(
        registry,
        context.get("quota_ledger_path"),
    )
    decision = DynamicRouteSelector(
        registry,
        quota_snapshots=quota_snapshots,
        route_states=load_runtime_route_states(
            registry,
            context.get("quota_ledger_path"),
        ),
    ).select(demand)
    if decision.get("status") != "selected":
        return None
    decision["demand"] = asdict(demand)
    checkpoint_id = context.get("checkpoint_id")
    if checkpoint_id:
        decision["checkpoint_id"] = str(checkpoint_id)
    selected_pool = str((decision.get("identity") or {}).get("credential_pool_id") or "")
    selected_snapshot = quota_snapshots.get(selected_pool) or {}
    if selected_snapshot.get("remaining_percent") is not None:
        decision["quota_before_percent"] = float(
            selected_snapshot["remaining_percent"]
        )
        decision["quota_snapshot_status"] = selected_snapshot.get("status")
    return registry.compile_legacy_profile(
        str(decision["route_id"]),
        resolved_mode=resolved_mode,
        resolved_tier=resolved_tier,
        decision=decision,
    )
