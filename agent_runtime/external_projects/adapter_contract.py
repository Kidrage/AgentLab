"""Adapter contract helpers for M1 external project records."""

from __future__ import annotations

from .models import ExternalProject


def validate_adapter_contract(project: ExternalProject) -> list[str]:
    issues: list[str] = []
    if not project.adapter_contract.expected_inputs:
        issues.append(f"{project.project_id}: adapter contract requires expected_inputs")
    if not project.adapter_contract.expected_outputs:
        issues.append(f"{project.project_id}: adapter contract requires expected_outputs")
    return issues
