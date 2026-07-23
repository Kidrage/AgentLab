from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.approvals.approval_policy import ApprovalPolicy, load_approval_policy


DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "executor_router.yml"


@dataclass
class ExecutorRouterPolicy:
    enabled: bool = True
    default_mode: str = "dry_run"
    routing: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=dict)
    provider_priority: dict[str, list[str]] = field(default_factory=dict)
    providers: list[dict[str, Any]] = field(default_factory=list)
    approval_policy: ApprovalPolicy = field(default_factory=ApprovalPolicy)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutorRouterPolicy":
        raw = data.get("executor_router", data) if isinstance(data, dict) else {}
        if not isinstance(raw, dict):
            raw = {}
        return cls(
            enabled=raw.get("enabled", True) is True,
            default_mode=str(raw.get("default_mode") or "dry_run"),
            routing=dict(raw.get("routing") or {}),
            budget=dict(raw.get("budget") or {}),
            safety=dict(raw.get("safety") or {}),
            provider_priority={
                str(key): [str(item) for item in value or []]
                for key, value in dict(raw.get("provider_priority") or {}).items()
            },
            providers=[dict(item) for item in raw.get("providers") or [] if isinstance(item, dict)],
        )


def load_executor_router_policy(path: Path | None = None) -> ExecutorRouterPolicy:
    policy_path = path or DEFAULT_POLICY_PATH
    if not policy_path.exists():
        return ExecutorRouterPolicy.from_dict({})
    data = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    policy = ExecutorRouterPolicy.from_dict(data)
    candidate_root = policy_path.parent.parent
    policy.approval_policy = load_approval_policy(candidate_root)
    return policy
