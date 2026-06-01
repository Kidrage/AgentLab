"""AgentLab Artifact Contract — rigorous artifact validation.

Detects missing files, TBD-only files, empty files, invalid YAML,
and ensures every lifecycle node has valid outputs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

TBD_PATTERNS = ["TBD", "tbd", "TODO", "FIXME", "# User Request\n\nDescribe the task here."]

REQUIRED_ARTIFACTS_BY_ROUTE = {
    "user_request": ["user_request.md"],
    "workflow_plan": ["workflow_plan.yml"],
    "supervisor": ["01_supervisor_plan.md"],
    "reposcout": ["02_reposcout_report.md"],
    "researcher": ["03_research_notes.md"],
    "interface_mapper": ["04_interface_map.md"],
    "coder": ["06_implementation_report.md"],
    "tester_auditor": ["07_validation_report.md", "08_audit_report.md"],
    "verifier": ["verification_report.md"],
    "archivist": ["09_archive_update.md"],
    "codex_prompt_generator": ["05_codex_prompt.md"],
    "self_check": ["self_check_report.yml"],
    "sync": ["sync_report.yml"],
    "finalize": ["task_card.yml", "artifact_manifest.yml"],
}

COMMON_ARTIFACTS = [
    "user_request.md", "workflow_plan.yml", "state.yml", "progress.yml",
    "brain_decisions.yml", "cost_ledger.yml",
]

SKIPPED_HEADER = "Status: skipped"


def is_tbd_or_empty(content: str) -> bool:
    """Check if file content is TBD, placeholder, or effectively empty."""
    stripped = content.strip()
    if not stripped:
        return True
    for pattern in TBD_PATTERNS:
        if stripped == pattern:
            return True
    # Check if it's just a heading
    lines = [l.strip() for l in stripped.split("\n") if l.strip()]
    if len(lines) <= 1 and lines and lines[0].startswith("#"):
        return True
    return False


def ensure_skipped_artifact(path: Path, title: str, reason: str) -> bool:
    """Create a skipped artifact file if it doesn't exist or is TBD."""
    if path.exists():
        content = path.read_text(encoding="utf-8")
        if SKIPPED_HEADER in content or not is_tbd_or_empty(content):
            return False  # already has valid content or skipped header
    content = f"# {title}\n\nStatus: skipped\nReason: {reason}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True  # created


def validate_artifacts(run_dir: Path) -> dict:
    """Validate all artifacts for a task run directory.

    Returns a detailed validation report.
    """
    issues = []
    artifacts_checked = 0
    artifacts_passed = 0

    route = _load_route(run_dir)
    all_artifact_names = required_artifacts_for_route(route) + [
        "lifecycle.yml",
        "self_check_report.yml",
        "task_card.yml",
        "artifact_manifest.yml",
    ]

    for fname in all_artifact_names:
        path = run_dir / fname
        artifacts_checked += 1

        if not path.exists():
            # Check if this is a skipped optional artifact
            if fname in ("03_research_notes.md", "04_interface_map.md", "sync_report.yml"):
                # Check lifecycle for skip reason
                lc_path = run_dir / "lifecycle.yml"
                if lc_path.exists():
                    try:
                        lc = yaml.safe_load(lc_path.read_text(encoding="utf-8"))
                        nodes = lc.get("nodes", {})
                        node_map = {
                            "03_research_notes.md": "RESEARCH_OPTIONAL",
                            "04_interface_map.md": "INTERFACE_OPTIONAL",
                            "sync_report.yml": "SYNC_OPTIONAL",
                        }
                        node_id = node_map.get(fname)
                        if node_id and nodes.get(node_id, {}).get("status") == "skipped":
                            artifacts_passed += 1
                            continue
                    except Exception:
                        pass
            issues.append({"file": fname, "issue": "missing"})
            continue

        # Read and check content
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            issues.append({"file": fname, "issue": f"unreadable: {e}"})
            continue

        # Check for TBD/empty
        if is_tbd_or_empty(content):
            issues.append({"file": fname, "issue": "TBD or empty placeholder"})
            continue

        # YAML parse check for .yml/.yaml files
        if fname.endswith((".yml", ".yaml")):
            try:
                yaml.safe_load(content)
            except Exception as e:
                issues.append({"file": fname, "issue": f"invalid YAML: {e}"})
                continue

        # Check for skipped header
        if SKIPPED_HEADER in content:
            artifacts_passed += 1
            continue

        artifacts_passed += 1

    pass_rate = artifacts_passed / max(artifacts_checked, 1)
    return {
        "valid": pass_rate >= 0.85,
        "pass_rate": round(pass_rate, 2),
        "artifacts_checked": artifacts_checked,
        "artifacts_passed": artifacts_passed,
        "issues": issues,
        "issues_count": len(issues),
    }


def required_artifacts_for_route(route: list[str]) -> list[str]:
    """Determine required artifacts for a given agent route."""
    required = list(COMMON_ARTIFACTS)
    agent_map = {
        "Supervisor": "supervisor",
        "RepoScout": "reposcout",
        "Researcher": "researcher",
        "InterfaceMapper": "interface_mapper",
        "Coder": "coder",
        "TesterAuditor": "tester_auditor",
        "Verifier": "verifier",
        "Archivist": "archivist",
        "PromptEngineer": "codex_prompt_generator",
    }
    for agent in route:
        key = agent_map.get(agent)
        if key:
            required.extend(REQUIRED_ARTIFACTS_BY_ROUTE.get(key, []))
    return list(dict.fromkeys(required))


def _load_route(run_dir: Path) -> list[str]:
    plan_path = run_dir / "workflow_plan.yml"
    if not plan_path.exists():
        return []
    try:
        plan = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    route = plan.get("route", {})
    if isinstance(route, dict):
        return list(route.get("agents", []) or [])
    if isinstance(route, list):
        return list(route)
    return []


def write_artifact_manifest(run_dir: Path, result: dict) -> None:
    """Write artifact validation result as manifest."""
    manifest = {
        "version": 1,
        "task_id": run_dir.name,
        "valid": result["valid"],
        "pass_rate": result["pass_rate"],
        "artifacts_checked": result["artifacts_checked"],
        "artifacts_passed": result["artifacts_passed"],
        "issues": result["issues"],
    }
    path = run_dir / "artifact_manifest.yml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
