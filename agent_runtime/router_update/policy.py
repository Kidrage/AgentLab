from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_runtime.router_update.models import EXTERNAL_PROVIDER_TYPES


def router_root(policy: dict[str, Any]) -> dict[str, Any]:
    raw = policy.get("executor_router", policy) if isinstance(policy, dict) else {}
    return raw if isinstance(raw, dict) else {}


def providers_by_id(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("provider_id")): item for item in router_root(policy).get("providers") or [] if isinstance(item, dict)}


def provider_priority(policy: dict[str, Any]) -> dict[str, list[str]]:
    return {
        str(task_type): [str(provider_id) for provider_id in providers or []]
        for task_type, providers in dict(router_root(policy).get("provider_priority") or {}).items()
    }


def is_external_provider(provider: dict[str, Any]) -> bool:
    return str(provider.get("provider_type") or "") in EXTERNAL_PROVIDER_TYPES or str(provider.get("provider_id") or "").startswith(("manual.", "api."))


def normalize_output_path(path: Path) -> str:
    parts = path.parts
    keep = parts[-3:] if len(parts) > 3 else parts
    return "/".join(keep)


def operation_path(provider_id: str, field: str) -> str:
    return f"executor_router.providers[{provider_id}].{field}"
