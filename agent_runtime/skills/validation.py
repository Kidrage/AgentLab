"""S4 Skill Trust / Permission / Sandbox validation orchestrator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .package_parser import parse_skill_package
from .permission_manifest import load_permission_policy, validate_permission_manifest
from .promotion import build_promotion_eligibility, load_promotion_policy
from .sandbox_runner import load_sandbox_policy, run_mock_sandbox
from .trust_scanner import load_trust_policy, scan_skill_trust


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def validate_skill_package_for_s4(
    package_path: Path | str,
    output_dir: Path | str,
    *,
    human_approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run metadata-only S4 validation and write reports."""

    package = Path(package_path)
    output = Path(output_dir)
    parsed = parse_skill_package(package)
    trust = scan_skill_trust(package, parsed, load_trust_policy())
    permissions = validate_permission_manifest(parsed, load_permission_policy())
    sandbox = run_mock_sandbox(package, parsed, trust, permissions, load_sandbox_policy())
    promotion = build_promotion_eligibility(
        parsed,
        trust,
        permissions,
        sandbox,
        human_approval=human_approval,
        policy=load_promotion_policy(),
    )
    summary = {
        "schema_version": 1,
        "skill_id": parsed.get("skill_id"),
        "package_path": str(package),
        "passed": bool(trust.get("passed") and permissions.get("passed") and sandbox.get("passed")),
        "promotion_eligible": promotion.get("promotion_eligible"),
        "dispatch_eligible": promotion.get("dispatch_eligible"),
        "reports": {
            "parsed_package": "parsed_package.yml",
            "trust_report": "trust_report.yml",
            "permission_report": "permission_report.yml",
            "sandbox_report": "sandbox_report.yml",
            "promotion_eligibility": "promotion_eligibility.yml",
        },
        "notes": [
            "S4 validation is metadata-only.",
            "No skill code, shell command, network call, or promotion was executed.",
        ],
    }

    _write_yaml(output / "parsed_package.yml", parsed)
    _write_yaml(output / "trust_report.yml", trust)
    _write_yaml(output / "permission_report.yml", permissions)
    _write_yaml(output / "sandbox_report.yml", sandbox)
    _write_yaml(output / "promotion_eligibility.yml", promotion)
    _write_yaml(output / "s4_validation_summary.yml", summary)
    return summary
