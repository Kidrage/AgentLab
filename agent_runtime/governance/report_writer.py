from __future__ import annotations

from pathlib import Path

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.governance.models import (
    CostGovernanceReport,
    GovernanceDecision,
    GovernanceInputBundle,
    GovernanceReport,
    ProviderCostProfile,
    ProviderPerformanceProfile,
    ProviderQuarantineRecommendation,
    ProviderRoutingRecommendation,
    ProviderWatchlistEntry,
    to_plain_data,
)


def write_governance_reports(
    output_dir: Path,
    input_bundle: GovernanceInputBundle,
    profiles: list[ProviderPerformanceProfile],
    cost_profiles: list[ProviderCostProfile],
    decisions: list[GovernanceDecision],
    watchlist: list[ProviderWatchlistEntry],
    quarantine: list[ProviderQuarantineRecommendation],
    routing_recommendations: list[ProviderRoutingRecommendation],
    routing_warnings: list[str] | None = None,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "input_manifest": output_dir / "governance_input_manifest.yml",
        "profiles": output_dir / "provider_performance_profiles.yml",
        "decisions": output_dir / "provider_governance_decisions.yml",
        "watchlist": output_dir / "provider_watchlist.yml",
        "quarantine": output_dir / "provider_quarantine_recommendations.yml",
        "cost_yml": output_dir / "cost_governance_report.yml",
        "cost_md": output_dir / "cost_governance_report.md",
        "routing_yml": output_dir / "routing_recommendations.yml",
        "routing_md": output_dir / "routing_recommendations.md",
        "report_md": output_dir / "provider_governance_report.md",
    }

    manifest = dict(input_bundle.manifest)
    manifest["warnings"] = list(input_bundle.warnings)
    atomic_write_yaml(paths["input_manifest"], manifest)
    atomic_write_yaml(paths["profiles"], {"providers": to_plain_data(profiles)})
    atomic_write_yaml(paths["decisions"], {"decisions": to_plain_data(decisions)})
    atomic_write_yaml(paths["watchlist"], {"watchlist": to_plain_data(watchlist)})
    atomic_write_yaml(paths["quarantine"], {"quarantine_recommendations": to_plain_data(quarantine)})
    atomic_write_yaml(paths["cost_yml"], to_plain_data(CostGovernanceReport(cost_profiles, _cost_warnings(cost_profiles))))
    atomic_write_text(paths["cost_md"], _cost_markdown(cost_profiles))
    atomic_write_yaml(
        paths["routing_yml"],
        {
            "apply_automatically": False,
            "recommendations": to_plain_data(routing_recommendations),
            "warnings": routing_warnings or [],
        },
    )
    atomic_write_text(paths["routing_md"], _routing_markdown(routing_recommendations, routing_warnings or []))
    governance = GovernanceReport(profiles, decisions, watchlist, quarantine, list(input_bundle.warnings))
    atomic_write_text(paths["report_md"], _governance_markdown(governance, cost_profiles, routing_recommendations, routing_warnings or [], manifest))
    return paths


def _cost_warnings(cost_profiles: list[ProviderCostProfile]) -> list[str]:
    return [f"{item.provider_id}: {note}" for item in cost_profiles for note in item.notes]


def _cost_markdown(cost_profiles: list[ProviderCostProfile]) -> str:
    lines = ["# Cost Governance Report", "", "| Provider | Cost Mode | Total | Average | Risk | Manual Approval |", "| --- | --- | ---: | ---: | --- | --- |"]
    for item in cost_profiles:
        lines.append(
            f"| {item.provider_id} | {item.cost_mode} | {_money(item.estimated_total_cost_usd)} | "
            f"{_money(item.estimated_average_cost_usd)} | {item.cost_risk_level} | {item.requires_manual_approval} |"
        )
    lines.extend(["", "Unknown cost events are treated as governance warnings and do not trigger provider execution."])
    return "\n".join(lines) + "\n"


def _routing_markdown(recommendations: list[ProviderRoutingRecommendation], warnings: list[str]) -> str:
    lines = [
        "# Routing Recommendations",
        "",
        "These recommendations are non-destructive and must be reviewed by a human before policy changes.",
        "",
        "| Provider | Recommendation | Priority Delta | Human Review | Apply Automatically |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for item in recommendations:
        lines.append(
            f"| {item.provider_id} | {item.recommendation} | {item.priority_delta} | "
            f"{item.requires_human_review} | {item.apply_automatically} |"
        )
    if warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines) + "\n"


def _governance_markdown(
    report: GovernanceReport,
    cost_profiles: list[ProviderCostProfile],
    routing_recommendations: list[ProviderRoutingRecommendation],
    routing_warnings: list[str],
    manifest: dict[str, object],
) -> str:
    lines = [
        "# AgentLab Provider Performance & Cost Governance Report",
        "",
        "## Summary",
        f"Processed {len(report.profiles)} provider profile(s) and generated recommendation-only routing feedback.",
        "",
        "## Input Artifacts",
    ]
    for key in ("execution_ledgers", "retry_attempt_ledgers", "provider_scorecards", "final_receipts"):
        lines.append(f"- {key}: {len(manifest.get(key) or [])}")
    if report.warnings:
        lines.append(f"- warnings: {len(report.warnings)}")
    lines.extend(["", "## Provider Performance"])
    for item in report.profiles:
        lines.append(
            f"- {item.provider_id}: attempts={item.attempts}, acceptance_rate={item.acceptance_rate}, "
            f"retry_rate={item.retry_rate}, blocked_rate={item.blocked_rate}, "
            f"average_quality_score={item.average_quality_score}, trend={item.trend}"
        )
    lines.extend(["", "## Cost Governance"])
    for item in cost_profiles:
        lines.append(f"- {item.provider_id}: cost_mode={item.cost_mode}, risk={item.cost_risk_level}, manual_approval={item.requires_manual_approval}")
    lines.extend(["", "## Governance Decisions"])
    for item in report.decisions:
        lines.append(f"- {item.provider_id}: {item.status} ({'; '.join(item.reasons) or 'no findings'})")
    lines.extend(["", "## Watchlist"])
    if report.watchlist:
        lines.extend(f"- {item.provider_id}: {'; '.join(item.reasons)}" for item in report.watchlist)
    else:
        lines.append("- None")
    lines.extend(["", "## Quarantine Recommendations"])
    if report.quarantine_recommendations:
        lines.extend(
            f"- {item.provider_id}: {'; '.join(item.reasons)}; test_recommendation_only={item.test_recommendation_only}"
            for item in report.quarantine_recommendations
        )
    else:
        lines.append("- None")
    lines.extend(["", "## Routing Recommendations"])
    for item in routing_recommendations:
        lines.append(f"- {item.provider_id}: {item.recommendation}; apply_automatically={item.apply_automatically}")
    lines.extend(["", "## Safety Notes"])
    lines.extend(
        [
            "- Governance reads local artifacts only.",
            "- It does not call Codex, Cline, ECC, API models, MCP servers, or network resources.",
            "- It never modifies executor_router.yml automatically.",
            "- Mock provider metrics are test signals, not real external provider capability claims.",
        ]
    )
    if routing_warnings or report.warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in [*report.warnings, *routing_warnings])
    lines.extend(["", "## Known Limitations"])
    lines.extend(
        [
            "- No real provider API cost query yet.",
            "- No real external execution is performed.",
            "- Recommendations are deterministic and artifact-based.",
            "- Router policy changes remain a human review step.",
        ]
    )
    return "\n".join(lines) + "\n"


def _money(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.6f}"
