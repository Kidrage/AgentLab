"""Render reports for M1 external project registry."""

from __future__ import annotations

from pathlib import Path

import yaml

from .registry import ExternalProjectRegistry


def write_external_project_risk_report(
    registry: ExternalProjectRegistry,
    out_dir: Path,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = registry.risk_report()
    yaml_path = out_dir / "external_project_risk_report.yml"
    md_path = out_dir / "external_project_risk_report.md"
    yaml_path.write_text(yaml.safe_dump(report, sort_keys=False), encoding="utf-8")
    lines = [
        "# External Project Risk Report",
        "",
        f"- Project count: {report['project_count']}",
        f"- Default enabled count: {report['default_enabled_count']}",
        f"- High-risk projects: {', '.join(report['high_risk_projects'])}",
        "",
        "## Safety Invariants",
        "",
    ]
    for key, value in report["safety_invariants"].items():
        lines.append(f"- {key}: {value}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return yaml_path, md_path
