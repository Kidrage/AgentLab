"""Budget gate checks for CostLedger v2."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import yaml

try:
    from atomic_io import atomic_write_text
except ImportError:  # pragma: no cover
    from agent_runtime.atomic_io import atomic_write_text


DEFAULT_BUDGET_POLICY = {
    "budget_policy": {
        "default_currency": "USD",
        "max_task_cost_usd": 0.20,
        "max_total_tokens": 200000,
        "require_approval_over_usd": 0.10,
        "allow_unknown_price": True,
        "unknown_price_warning": True,
    }
}


@dataclass
class BudgetDecision:
    status: str
    task_id: str | None = None
    approval_required: bool = False
    warnings: list[str] | None = None
    estimated_cost_usd: float | None = None
    known_cost_usd: float | None = None
    unknown_priced_calls: list[dict[str, Any]] | None = None
    total_tokens: int = 0
    policy: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["warnings"] = self.warnings or []
        data["unknown_priced_calls"] = self.unknown_priced_calls or []
        return data


def load_budget_policy(agentlab_root: Path) -> dict[str, Any]:
    path = agentlab_root / "config" / "budget_policy.yml"
    if not path.exists():
        return DEFAULT_BUDGET_POLICY["budget_policy"]
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        loaded = {}
    policy = dict(DEFAULT_BUDGET_POLICY["budget_policy"])
    policy.update(loaded.get("budget_policy", loaded) or {})
    return policy


def evaluate_budget_gate(ledger: Any, policy: dict[str, Any] | None = None) -> BudgetDecision:
    policy = policy or DEFAULT_BUDGET_POLICY["budget_policy"]
    total = ledger.total() if hasattr(ledger, "total") else ledger.get("total", {})
    task_id = getattr(ledger, "task_id", None) if not isinstance(ledger, dict) else ledger.get("task_id")
    total_tokens = sum(
        int(total.get(key) or 0)
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "reasoning_tokens",
            "image_input_tokens",
            "audio_input_tokens",
        )
    )
    estimated_cost = total.get("estimated_cost_usd")
    unknown_priced_calls = list(total.get("unknown_priced_calls") or [])
    warnings: list[str] = []
    approval_required = False

    approval_threshold = policy.get("require_approval_over_usd")
    if estimated_cost is not None and approval_threshold is not None:
        if float(estimated_cost) > float(approval_threshold):
            approval_required = True
            warnings.append(
                f"Estimated cost ${estimated_cost:.6f} exceeds approval threshold ${float(approval_threshold):.2f}."
            )

    max_task_cost = policy.get("max_task_cost_usd")
    if estimated_cost is not None and max_task_cost is not None and float(estimated_cost) > float(max_task_cost):
        warnings.append(f"Estimated cost ${estimated_cost:.6f} exceeds max task budget ${float(max_task_cost):.2f}.")

    max_tokens = int(policy.get("max_total_tokens") or 0)
    has_unknown_price = any(
        (call.get("estimated_cost_usd") is None if isinstance(call, dict) else call.estimated_cost_usd is None)
        for call in (ledger.get("calls", []) if isinstance(ledger, dict) else getattr(ledger, "calls", []))
    )
    if has_unknown_price and max_tokens and total_tokens > max_tokens and policy.get("unknown_price_warning", True):
        warnings.append("Unknown pricing with high token usage; cost was not converted to money.")
    if unknown_priced_calls and any(
        (call.get("estimated_cost_usd") is not None if isinstance(call, dict) else call.estimated_cost_usd is not None)
        for call in (ledger.get("calls", []) if isinstance(ledger, dict) else getattr(ledger, "calls", []))
    ):
        warnings.append("Partial pricing: some calls have unknown prices and were not converted to money.")

    status = "pending_approval" if approval_required else ("warning" if warnings else "ok")
    return BudgetDecision(
        task_id=task_id,
        status=status,
        approval_required=approval_required,
        warnings=warnings,
        estimated_cost_usd=estimated_cost,
        known_cost_usd=estimated_cost,
        unknown_priced_calls=unknown_priced_calls,
        total_tokens=total_tokens,
        policy={
            "max_task_cost_usd": policy.get("max_task_cost_usd"),
            "require_approval_over_usd": policy.get("require_approval_over_usd"),
            "max_total_tokens": policy.get("max_total_tokens"),
        },
    )


def write_budget_decision(run_dir: Path, decision: BudgetDecision) -> Path | None:
    path = run_dir / "budget_gate_decision.yml"
    atomic_write_text(path, yaml.safe_dump(decision.as_dict(), sort_keys=False), encoding="utf-8")
    if decision.approval_required:
        md = [
            "# Budget Approval Required",
            "",
            f"- Status: {decision.status}",
            f"- Estimated cost USD: {decision.estimated_cost_usd}",
            f"- Total tokens: {decision.total_tokens}",
            "",
            "## Warnings",
        ]
        md.extend(f"- {warning}" for warning in (decision.warnings or []))
        atomic_write_text(run_dir / "BUDGET_DECISION_REQUIRED.md", "\n".join(md) + "\n", encoding="utf-8")
    return path
