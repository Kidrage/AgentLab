"""CostLedger v2 model and artifact writers."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import yaml

try:
    from atomic_io import atomic_write_text
except ImportError:  # pragma: no cover
    from agent_runtime.atomic_io import atomic_write_text


@dataclass
class CostCall:
    stage: str
    agent: str
    provider: str | None = None
    model_alias: str | None = None
    provider_model_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    image_input_tokens: int = 0
    audio_input_tokens: int = 0
    usage_source: str = "unknown"
    price_source: str = "unknown"
    estimated_cost_usd: float | None = None
    pricing_confidence: str = "none"
    started_at: str | None = None
    finished_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CostLedger:
    task_id: str
    currency: str = "USD"
    calls: list[CostCall] = field(default_factory=list)

    def total(self) -> dict[str, Any]:
        totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "reasoning_tokens": 0,
            "image_input_tokens": 0,
            "audio_input_tokens": 0,
            "estimated_cost_usd": None,
            "pricing_confidence": "none",
            "pricing_status": "unknown",
            "unknown_priced_calls": [],
        }
        known_cost = 0.0
        has_cost = False
        unknown_calls: list[dict[str, Any]] = []
        confidence_rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
        max_confidence = 0
        for call in self.calls:
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_read_tokens",
                "cache_write_tokens",
                "reasoning_tokens",
                "image_input_tokens",
                "audio_input_tokens",
            ):
                totals[key] += int(getattr(call, key) or 0)
            if call.estimated_cost_usd is not None:
                known_cost += float(call.estimated_cost_usd)
                has_cost = True
            else:
                unknown_calls.append({
                    "stage": call.stage,
                    "model_alias": call.model_alias,
                    "provider_model_id": call.provider_model_id,
                })
            max_confidence = max(max_confidence, confidence_rank.get(call.pricing_confidence, 0))
        if has_cost:
            totals["estimated_cost_usd"] = round(known_cost, 8)
        totals["unknown_priced_calls"] = unknown_calls
        if self.calls and not unknown_calls:
            totals["pricing_status"] = "complete"
        elif self.calls and len(unknown_calls) < len(self.calls):
            totals["pricing_status"] = "partial"
        totals["pricing_confidence"] = next(
            name for name, rank in confidence_rank.items() if rank == max_confidence
        )
        return totals

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "currency": self.currency,
            "total": self.total(),
            "calls": [call.as_dict() for call in self.calls],
        }


def render_cost_summary(ledger: CostLedger) -> str:
    total = ledger.total()
    cost = total["estimated_cost_usd"]
    cost_text = "unknown" if cost is None else f"${cost:.6f}"
    lines = [
        "# Cost Summary",
        "",
        f"Task ID: {ledger.task_id}",
        f"Total input tokens: {total['input_tokens']}",
        f"Total output tokens: {total['output_tokens']}",
        f"Pricing status: {total['pricing_status']}",
        f"Total estimated cost: {cost_text}",
        f"Pricing confidence: {total['pricing_confidence']}",
        "",
    ]
    unknown_calls = total.get("unknown_priced_calls") or []
    if unknown_calls:
        lines.extend(["Unknown priced calls:"])
        for item in unknown_calls:
            model = item.get("model_alias") or item.get("provider_model_id") or "unknown"
            lines.append(f"- {model}")
        lines.append("")
    lines.extend([
        "",
        "## Calls",
        "",
        "| Stage | Agent | Model | Input | Output | Estimated Cost | Usage Source | Price Source |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ])
    for call in ledger.calls:
        model = call.model_alias or call.provider_model_id or "unknown"
        call_cost = "unknown" if call.estimated_cost_usd is None else f"${call.estimated_cost_usd:.6f}"
        lines.append(
            f"| {call.stage} | {call.agent} | {model} | {call.input_tokens} | "
            f"{call.output_tokens} | {call_cost} | {call.usage_source} | {call.price_source} |"
        )
    lines.extend([
        "",
        "## Notes",
        "- Unknown prices are not converted to money.",
        "- External IDE/Cline/Codex subscription usage is not included unless explicitly reported.",
        "",
    ])
    return "\n".join(lines)


def write_cost_artifacts(run_dir: Path, ledger: CostLedger) -> tuple[Path, Path]:
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = run_dir / "cost_ledger.yml"
    summary_path = run_dir / "cost_summary.md"
    atomic_write_text(
        ledger_path,
        yaml.safe_dump(ledger.as_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    atomic_write_text(summary_path, render_cost_summary(ledger), encoding="utf-8")
    return ledger_path, summary_path
