"""Legacy closure-artifact validator retained for old task runs.

Responsibilities:
1. Check required files exist.
2. Check YAML parses.
3. Check handoff packet schema.
4. Check report sequence.
5. Check whether task can resume.

CLI:
    ./agentlab.sh codex-verify-artifacts --project <ProjectName> --task-id <task_id>
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml


REQUIRED_REPORTS = [
    "user_request.md",
    "workflow_plan.yml",
    "state.yml",
    "progress.yml",
    "01_supervisor_plan.md",
    "02_reposcout_report.md",
]

REQUIRED_CODER_REPORTS = [
    "03_research_notes.md",
    "04_interface_map.md",
    "06_implementation_report.md",
    "07_validation_report.md",
    "08_audit_report.md",
    "09_archive_update.md",
    "artifact_lineage.yml",
    "artifact_promotion_plan.yml",
    "archive_receipt.yml",
]

REQUIRED_ARTIFACT_GROUPS = [
    ("codex_driver_manifest.yml", "artifact_manifest.yml"),
    ("00_preflight_report.md", "lifecycle.yml"),
    ("05_codex_prompt.md", "05_coder_prompt.md"),
]

REQUIRED_DIFFS = [
    "diffs/pre_coder.diff",
    "diffs/post_coder.diff",
]

REQUIRED_SUBDIRS = [
    "checkpoints",
    "command_logs",
    "sync",
]

HANDOFF_SCHEMA_KEYS = [
    "task_id",
    "project",
    "execution_mode",
    "status",
    "last_completed_agent",
    "next_agent",
    "resume_available",
    "artifacts",
    "code_state",
    "validation",
    "resume_instructions",
]


def _is_yaml_file(path: Path) -> bool:
    return path.suffix in (".yml", ".yaml")


def _parse_yaml(path: Path) -> Optional[dict]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        return None
    except Exception:
        return None


def validate_artifacts(
    project_root: Path,
    task_id: str,
) -> dict:
    """Run the legacy numbered-report validation checks for a task.

    Args:
        project_root: Path to the project directory (projects/<ProjectName>/).
        task_id: Task run identifier (e.g. task_0022).

    Returns:
        A dict with validation results:
            {
                "task_id": str,
                "all_required_reports_exist": bool,
                "missing_reports": list[str],
                "yaml_files_parse": dict[str, bool],
                "handoff_packet_valid": bool,
                "handoff_packet_issues": list[str],
                "report_sequence_ok": bool,
                "can_resume": bool,
                "resume_from_agent": Optional[str],
                "result": "pass" | "fail",
            }
    """
    run_dir = project_root / "runs" / task_id
    result: dict = {
        "task_id": task_id,
        "run_dir": str(run_dir),
        "all_required_reports_exist": True,
        "missing_reports": [],
        "yaml_files_parse": {},
        "handoff_packet_valid": False,
        "handoff_packet_issues": [],
        "project_artifact_governance_issues": [],
        "report_sequence_ok": True,
        "can_resume": False,
        "resume_from_agent": None,
        "result": "pass",
    }

    # ── 1. Check required reports exist ────────────────────────────────
    all_required = REQUIRED_REPORTS + REQUIRED_CODER_REPORTS
    for report in all_required:
        p = run_dir / report
        if not p.exists():
            result["missing_reports"].append(report)
            result["all_required_reports_exist"] = False

    for group in REQUIRED_ARTIFACT_GROUPS:
        if not any((run_dir / report).exists() for report in group):
            result["missing_reports"].append(" | ".join(group))
            result["all_required_reports_exist"] = False

    if result["missing_reports"]:
        result["result"] = "fail"

    # ── 2. Check required subdirectories ────────────────────────────────
    for subdir in REQUIRED_SUBDIRS:
        if not (run_dir / subdir).is_dir():
            result.setdefault("missing_subdirs", []).append(subdir)

    # ── 3. Check required diffs ─────────────────────────────────────────
    for diff_file in REQUIRED_DIFFS:
        if not (run_dir / diff_file).exists():
            result.setdefault("missing_diffs", []).append(diff_file)

    # ── 4. Check YAML files parse ───────────────────────────────────────
    for report in all_required + [item for group in REQUIRED_ARTIFACT_GROUPS for item in group]:
        p = run_dir / report
        if p.exists() and _is_yaml_file(p):
            parsed = _parse_yaml(p)
            result["yaml_files_parse"][report] = parsed is not None
            if parsed is None:
                result["result"] = "fail"

    # Also check yaml files in sync/ and diffs may not be needed
    for yml_file in run_dir.glob("sync/*.yml"):
        parsed = _parse_yaml(yml_file)
        result["yaml_files_parse"][str(yml_file.relative_to(run_dir))] = parsed is not None

    # ── 5. Check handoff packet schema ──────────────────────────────────
    handoff_path = run_dir / "handoff_packet.yml"
    if handoff_path.exists():
        handoff_data = _parse_yaml(handoff_path)
        if handoff_data is None:
            result["handoff_packet_issues"].append("handoff_packet.yml does not parse as YAML")
        else:
            missing_keys = [k for k in HANDOFF_SCHEMA_KEYS if k not in handoff_data]
            if missing_keys:
                result["handoff_packet_issues"].append(f"Missing schema keys: {missing_keys}")
            else:
                result["handoff_packet_valid"] = True

            # Check resume info
            if handoff_data.get("resume_available") and handoff_data.get("next_agent"):
                result["can_resume"] = True
                result["resume_from_agent"] = handoff_data.get("next_agent")
    else:
        result["handoff_packet_issues"].append("handoff_packet.yml not found")
        result["result"] = "fail"

    # ── 6. Check report sequence ────────────────────────────────────────
    # Reports should follow the pattern: 00, 01, 02, ..., 09
    for i in range(10):
        report_name = f"{i:02d}_*.md"
        matching = list(run_dir.glob(report_name))
        if not matching:
            result["report_sequence_ok"] = False

    # ── 7. Project artifact governance ─────────────────────────────────
    if project_root.parent.name == "projects":
        agentlab_root = project_root.parent.parent
        try:
            from project_artifact_steward import validate_project_artifact_governance

            governance_issues = validate_project_artifact_governance(
                agentlab_root,
                project_root.name,
                task_id,
                run_dir=run_dir,
            )
        except Exception as exc:
            governance_issues = [f"Project Artifact Steward validation failed: {type(exc).__name__}: {exc}"]
        result["project_artifact_governance_issues"] = governance_issues
        if governance_issues:
            result["result"] = "fail"

    return result


def print_validation_report(result: dict) -> None:
    """Pretty-print the validation results (for CLI use)."""
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    console = Console()

    console.print(Panel(f"[bold]Codex Artifact Validation — {result['task_id']}[/bold]"))

    # Required reports
    table = Table("Report", "Status")
    all_required = REQUIRED_REPORTS + REQUIRED_CODER_REPORTS
    for report in all_required:
        exists = report not in result.get("missing_reports", [])
        table.add_row(report, "✅" if exists else "❌")
    for group in REQUIRED_ARTIFACT_GROUPS:
        label = " | ".join(group)
        exists = label not in result.get("missing_reports", [])
        table.add_row(label, "✅" if exists else "❌")
    console.print(table)

    # YAML parse
    if result.get("yaml_files_parse"):
        yaml_table = Table("YAML File", "Parses")
        for fname, ok in result["yaml_files_parse"].items():
            yaml_table.add_row(fname, "✅" if ok else "❌")
        console.print(yaml_table)

    # Handoff
    if result["handoff_packet_issues"]:
        for issue in result["handoff_packet_issues"]:
            console.print(f"[yellow]Handoff: {issue}[/yellow]")
    else:
        console.print("[green]Handoff packet: valid[/green]")

    # Resume
    if result["can_resume"]:
        console.print(f"[green]Can resume from: {result['resume_from_agent']}[/green]")

    for issue in result.get("project_artifact_governance_issues") or []:
        console.print(f"[red]Artifact governance: {issue}[/red]")

    # Final
    status_color = "green" if result["result"] == "pass" else "red"
    console.print(f"\n[bold {status_color}]Result: {result['result']}[/bold {status_color}]")


if __name__ == "__main__":
    # Simple CLI for standalone usage
    import sys
    project_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("projects/AgentLab")
    task_id = sys.argv[2] if len(sys.argv) > 2 else "task_0022"
    result = validate_artifacts(project_root, task_id)
    print_validation_report(result)
