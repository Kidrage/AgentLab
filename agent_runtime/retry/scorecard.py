from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.retry.attempt_ledger import redact_for_ledger
from agent_runtime.retry.models import ProviderScorecardEntry, RetryPolicy, to_plain_data


def load_provider_scorecard(path: Path) -> dict[str, Any]:
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict):
            data.setdefault("providers", [])
            return data
    return {"providers": []}


def write_provider_scorecard(path: Path, scorecard: dict[str, Any]) -> None:
    atomic_write_yaml(path, redact_for_ledger(scorecard))


def update_provider_scorecard(
    path: Path,
    provider_id: str,
    provider_type: str,
    verdict: str | None,
    policy: RetryPolicy,
    notes: list[str] | None = None,
) -> ProviderScorecardEntry:
    scorecard = load_provider_scorecard(path)
    entries = {item.get("provider_id"): ProviderScorecardEntry(**_entry_kwargs(item)) for item in scorecard["providers"]}
    entry = entries.get(provider_id) or ProviderScorecardEntry(
        provider_id=provider_id,
        provider_type=provider_type,
        notes=notes or [],
    )
    if notes:
        entry.notes = list(dict.fromkeys([*entry.notes, *notes]))
    normalized = (verdict or "UNKNOWN").upper()
    entry.attempts += 1
    entry.last_verdict = normalized
    if normalized == "PASS":
        entry.passes += 1
    elif normalized == "PASS_WITH_WARNINGS":
        entry.pass_with_warnings += 1
    elif normalized == "NEEDS_REVISION":
        entry.needs_revision += 1
    elif normalized == "FAIL":
        entry.fails += 1
    elif normalized == "BLOCKED":
        entry.blocked += 1
    entry.total_quality_score += quality_score_for_verdict(normalized, policy)
    entry.average_quality_score = round(entry.total_quality_score / max(entry.attempts, 1), 3)
    entries[provider_id] = entry
    scorecard["providers"] = [to_plain_data(item) for item in entries.values()]
    write_provider_scorecard(path, scorecard)
    return entry


def quality_score_for_verdict(verdict: str, policy: RetryPolicy) -> float:
    scores = policy.scorecard
    return {
        "PASS": float(scores.get("quality_score_pass", 1.0)),
        "PASS_WITH_WARNINGS": float(scores.get("quality_score_pass_with_warnings", 0.75)),
        "NEEDS_REVISION": float(scores.get("quality_score_needs_revision", 0.35)),
        "FAIL": float(scores.get("quality_score_fail", 0.1)),
        "BLOCKED": float(scores.get("quality_score_blocked", 0.0)),
    }.get(verdict, 0.0)


def _entry_kwargs(item: dict[str, Any]) -> dict[str, Any]:
    allowed = ProviderScorecardEntry.__dataclass_fields__.keys()
    return {key: item.get(key) for key in allowed if key in item}
