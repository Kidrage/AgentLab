from __future__ import annotations

from collections import defaultdict
from typing import Any

from agent_runtime.governance.models import (
    GovernanceDecision,
    GovernanceInputBundle,
    ProviderCostProfile,
    ProviderGovernancePolicy,
    ProviderPerformanceProfile,
    ProviderQuarantineRecommendation,
    ProviderWatchlistEntry,
)


QUALITY_SCORES = {
    "PASS": 1.0,
    "PASS_WITH_WARNINGS": 0.75,
    "NEEDS_REVISION": 0.35,
    "FAIL": 0.1,
    "BLOCKED": 0.0,
}


def build_provider_performance_profiles(
    input_bundle: GovernanceInputBundle,
    policy: ProviderGovernancePolicy,
) -> list[ProviderPerformanceProfile]:
    by_provider: dict[str, dict[str, Any]] = defaultdict(_empty_stats)
    verdict_history: dict[str, list[str]] = defaultdict(list)

    for scorecard in input_bundle.provider_scorecards:
        for item in scorecard.get("providers") or []:
            if not isinstance(item, dict):
                continue
            provider_id = str(item.get("provider_id") or "")
            if not provider_id:
                continue
            stats = by_provider[provider_id]
            stats["provider_type"] = str(item.get("provider_type") or stats["provider_type"] or "unknown")
            stats["attempts"] += int(item.get("attempts") or 0)
            stats["pass_count"] += int(item.get("passes") or 0)
            stats["pass_with_warnings_count"] += int(item.get("pass_with_warnings") or 0)
            stats["needs_revision_count"] += int(item.get("needs_revision") or 0)
            stats["fail_count"] += int(item.get("fails") or 0)
            stats["blocked_count"] += int(item.get("blocked") or 0)
            stats["quality_total"] += float(item.get("total_quality_score") or 0.0)
            if item.get("last_verdict"):
                stats["last_verdict"] = str(item["last_verdict"]).upper()
                verdict_history[provider_id].append(stats["last_verdict"])
            stats["notes"].extend(str(note) for note in item.get("notes") or [])

    for ledger in input_bundle.retry_attempt_ledgers:
        for attempt in ledger.get("attempts") or []:
            if not isinstance(attempt, dict):
                continue
            provider_id = str(attempt.get("provider_id") or "")
            if not provider_id:
                continue
            stats = by_provider[provider_id]
            stats["provider_type"] = str(attempt.get("provider_type") or stats["provider_type"] or "unknown")
            retry_decision = str(attempt.get("retry_decision") or "").upper()
            status = str(attempt.get("status") or "").lower()
            if retry_decision == "RETRY" or "failed" in status:
                stats["retry_count"] += 1
            if attempt.get("estimated_cost_usd") is None:
                stats["unknown_cost_events"] += 1

    for receipt in input_bundle.final_receipts:
        provider_id = _receipt_provider_id(receipt)
        if not provider_id:
            continue
        stats = by_provider[provider_id]
        accepted = bool(receipt.get("accepted", False)) or "acceptance" in str(receipt.get("receipt_type", "")).lower()
        if accepted:
            stats["accepted"] += 1
        else:
            stats["rejected"] += 1

    profiles: list[ProviderPerformanceProfile] = []
    min_attempts = int(policy.minimum_data.get("min_attempts_for_scoring", 2))
    for provider_id, stats in sorted(by_provider.items()):
        attempts = int(stats["attempts"])
        accepted = int(stats["accepted"] or (stats["pass_count"] + stats["pass_with_warnings_count"]))
        rejected = int(stats["rejected"] or (stats["needs_revision_count"] + stats["fail_count"] + stats["blocked_count"]))
        quality_total = float(stats["quality_total"])
        if quality_total <= 0.0 and attempts:
            quality_total = (
                stats["pass_count"] * QUALITY_SCORES["PASS"]
                + stats["pass_with_warnings_count"] * QUALITY_SCORES["PASS_WITH_WARNINGS"]
                + stats["needs_revision_count"] * QUALITY_SCORES["NEEDS_REVISION"]
                + stats["fail_count"] * QUALITY_SCORES["FAIL"]
                + stats["blocked_count"] * QUALITY_SCORES["BLOCKED"]
            )
        notes = list(dict.fromkeys(stats["notes"]))
        if stats["provider_type"] == "mock_executor":
            notes.append("mock data; do not interpret as real external provider performance")
        profiles.append(
            ProviderPerformanceProfile(
                provider_id=provider_id,
                provider_type=str(stats["provider_type"] or "unknown"),
                attempts=attempts,
                accepted=accepted,
                rejected=rejected,
                retry_count=int(stats["retry_count"]),
                pass_count=int(stats["pass_count"]),
                pass_with_warnings_count=int(stats["pass_with_warnings_count"]),
                needs_revision_count=int(stats["needs_revision_count"]),
                fail_count=int(stats["fail_count"]),
                blocked_count=int(stats["blocked_count"]),
                acceptance_rate=round(accepted / attempts, 3) if attempts else 0.0,
                retry_rate=round(int(stats["retry_count"]) / attempts, 3) if attempts else 0.0,
                blocked_rate=round(int(stats["blocked_count"]) / attempts, 3) if attempts else 0.0,
                average_quality_score=round(quality_total / attempts, 3) if attempts else 0.0,
                last_verdict=stats["last_verdict"],
                trend=_trend(verdict_history[provider_id], attempts, min_attempts),
                notes=notes,
            )
        )
    return profiles


def derive_governance_decisions(
    provider_profiles: list[ProviderPerformanceProfile],
    cost_profiles: list[ProviderCostProfile],
    policy: ProviderGovernancePolicy,
) -> list[GovernanceDecision]:
    costs = {item.provider_id: item for item in cost_profiles}
    min_scoring = int(policy.minimum_data.get("min_attempts_for_scoring", 2))
    min_quarantine = int(policy.minimum_data.get("min_attempts_for_quarantine", 3))
    thresholds = policy.thresholds
    decisions: list[GovernanceDecision] = []
    for profile in provider_profiles:
        cost_profile = costs.get(profile.provider_id)
        reasons: list[str] = []
        status = "HEALTHY"
        action = "keep"
        if profile.attempts < min_scoring:
            status = "INSUFFICIENT_DATA"
            action = "insufficient_data"
            reasons.append("not enough attempts for scoring")
        elif profile.blocked_rate >= float(thresholds.get("high_blocked_rate", 0.20)):
            status = "QUARANTINE_RECOMMENDED"
            action = "quarantine"
            reasons.append("blocked rate exceeds threshold")
        elif (
            profile.acceptance_rate < float(thresholds.get("quarantine_acceptance_rate_below", 0.35))
            and profile.attempts >= min_quarantine
        ):
            status = "QUARANTINE_RECOMMENDED"
            action = "quarantine"
            reasons.append("acceptance rate below quarantine threshold")
        elif profile.retry_rate > float(thresholds.get("high_retry_rate", 0.60)):
            status = "WATCHLIST"
            action = "watchlist"
            reasons.append("retry rate exceeds threshold")
        elif profile.acceptance_rate < float(thresholds.get("watchlist_acceptance_rate", 0.50)):
            status = "WATCHLIST"
            action = "watchlist"
            reasons.append("acceptance rate below watchlist threshold")
        elif profile.average_quality_score < float(thresholds.get("min_average_quality_score", 0.60)):
            status = "DOWNGRADED"
            action = "downgrade"
            reasons.append("average quality score below threshold")

        if cost_profile and cost_profile.requires_manual_approval:
            if status == "HEALTHY":
                status = "MANUAL_APPROVAL_REQUIRED"
                action = "require_manual_approval"
            reasons.append("unknown cost mode requires manual approval")

        decisions.append(GovernanceDecision(provider_id=profile.provider_id, status=status, reasons=reasons, recommended_action=action))
    return decisions


def build_watchlist(decisions: list[GovernanceDecision]) -> list[ProviderWatchlistEntry]:
    return [
        ProviderWatchlistEntry(item.provider_id, item.reasons, item.status == "MANUAL_APPROVAL_REQUIRED")
        for item in decisions
        if item.status in {"WATCHLIST", "DOWNGRADED", "MANUAL_APPROVAL_REQUIRED"}
    ]


def build_quarantine_recommendations(
    decisions: list[GovernanceDecision],
    profiles: list[ProviderPerformanceProfile],
) -> list[ProviderQuarantineRecommendation]:
    by_provider = {item.provider_id: item for item in profiles}
    return [
        ProviderQuarantineRecommendation(
            provider_id=item.provider_id,
            reasons=item.reasons,
            requires_human_review=True,
            test_recommendation_only=by_provider.get(item.provider_id, ProviderPerformanceProfile(item.provider_id, "unknown")).provider_type
            == "mock_executor",
        )
        for item in decisions
        if item.status == "QUARANTINE_RECOMMENDED"
    ]


def _empty_stats() -> dict[str, Any]:
    return {
        "provider_type": "unknown",
        "attempts": 0,
        "accepted": 0,
        "rejected": 0,
        "retry_count": 0,
        "pass_count": 0,
        "pass_with_warnings_count": 0,
        "needs_revision_count": 0,
        "fail_count": 0,
        "blocked_count": 0,
        "quality_total": 0.0,
        "last_verdict": None,
        "notes": [],
        "unknown_cost_events": 0,
    }


def _receipt_provider_id(receipt: dict[str, Any]) -> str:
    if receipt.get("provider_id"):
        return str(receipt["provider_id"])
    attempts = receipt.get("attempts") or []
    if isinstance(attempts, list) and attempts and isinstance(attempts[-1], dict):
        return str(attempts[-1].get("provider_id") or "")
    return ""


def _trend(verdicts: list[str], attempts: int, min_attempts: int) -> str:
    if attempts < min_attempts or len(verdicts) < 2:
        return "insufficient_data"
    first = QUALITY_SCORES.get(verdicts[0], 0.0)
    last = QUALITY_SCORES.get(verdicts[-1], 0.0)
    if last > first:
        return "improving"
    if last < first:
        return "degrading"
    return "stable"
