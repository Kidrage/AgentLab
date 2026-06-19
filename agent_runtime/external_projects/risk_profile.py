"""Risk validation for M1 external projects."""

from __future__ import annotations

from .models import ExternalProject


HIGH_RISK_REASONS = {
    "platform_terms_risk",
    "self_execution_research",
    "external_dependency",
    "channel_operation_reference",
}


def project_requires_approval(project: ExternalProject) -> bool:
    if project.risk.level == "high":
        return True
    return any(reason in HIGH_RISK_REASONS for reason in project.risk.reasons)


def validate_project_safety(project: ExternalProject) -> list[str]:
    issues: list[str] = []
    if project.default_enabled:
        issues.append(f"{project.project_id}: default_enabled must be false")
    if project.integration_stage != "registry_only":
        issues.append(f"{project.project_id}: integration_stage must be registry_only")
    if project_requires_approval(project) and not project.risk.requires_approval:
        issues.append(f"{project.project_id}: high-risk project must require approval")
    if project.permissions.get("shell") is not False:
        issues.append(f"{project.project_id}: shell permission must be false")
    if project.permissions.get("network") is not False:
        issues.append(f"{project.project_id}: network permission must be false")
    return issues
