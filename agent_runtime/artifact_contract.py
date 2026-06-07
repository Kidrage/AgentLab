"""AgentLab Artifact Contract - rigorous artifact validation.

Detects missing files, TBD-only files, empty files, invalid YAML,
semantic placeholders, and ensures every lifecycle node has valid outputs.
"""

from __future__ import annotations

from pathlib import Path
import re

import yaml

TBD_PATTERNS = ["TBD", "tbd", "TODO", "FIXME", "# User Request\n\nDescribe the task here."]
UNEXECUTED_TOOL_CALL_PATTERNS = [
    "<tool_call",
    "</tool_call>",
    "\"tool_calls\"",
    "'tool_calls'",
    "\"function_call\"",
    "'function_call'",
]
EXECUTION_PLACEHOLDER_PATTERNS = [
    "Commands run: None",
    "Commands run: none",
    "Commands run: N/A",
    "Commands run: n/a",
    "no execution occurred",
    "plan-only phase",
    "Coder phase not executed",
    "no implementation work was performed",
    "No implementation work performed",
    "No source edits have been performed",
    "No source files were modified",
    "no source files were modified",
    "no upload performed",
    "No validation commands were executed",
    "validation was not executed",
    "audit was not executed",
    "Execution phase artifacts not yet provided",
    "pre-execution state",
]
EXECUTION_REQUIRED_FILES = {
    "06_implementation_report.md",
    "implementation_report.md",
    "07_validation_report.md",
    "validation_report.md",
    "08_audit_report.md",
    "audit_report.md",
}
ARCHIVIST_PLACEHOLDER_PATTERNS = [
    "no agent_docs updates were applied",
    "agent_docs updates were not applied",
    "memory updates were not applied",
    "no durable memory updates",
    "no project memory was updated",
]
USER_DECISION_CLAIM_PATTERNS = [
    "created user_decision_required.md",
    "generated user_decision_required.md",
    "wrote user_decision_required.md",
    "written user_decision_required.md",
    "deliverables: user_decision_required.md",
    "output: user_decision_required.md",
]

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
    "codex_prompt_generator": ["05_coder_prompt.md"],
    "self_check": ["self_check_report.yml"],
    "sync": ["sync_report.yml"],
    "finalize": ["task_card.yml", "artifact_manifest.yml"],
}

COMMON_ARTIFACTS = [
    "user_request.md", "workflow_plan.yml", "state.yml", "progress.yml",
    "task_snapshot.yml", "brain_decisions.yml", "cost_ledger.yml",
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

        content_issues = artifact_content_issues(fname, content, run_dir)
        if content_issues:
            issues.extend({"file": fname, "issue": issue} for issue in content_issues)
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

    # ── Snapshot drift detection ──
    snapshot_path = run_dir / "task_snapshot.yml"
    snapshot_drift = False
    if snapshot_path.exists():
        try:
            snapshot_data = yaml.safe_load(snapshot_path.read_text(encoding="utf-8")) or {}
            drift = snapshot_data.get("drift", {}) or {}
            status_mismatch = snapshot_data.get("status_mismatch", False)
            unknown_sources = [
                k for k, v in (snapshot_data.get("sources", {}) or {}).items()
                if v in ("unknown", None, "")
            ]
            if status_mismatch:
                snapshot_drift = True
                issues.append({"file": "task_snapshot.yml", "issue": "status_mismatch: state, progress, and lifecycle disagree"})
            if unknown_sources:
                snapshot_drift = True
                issues.append({"file": "task_snapshot.yml", "issue": f"unknown source status for: {', '.join(unknown_sources)}"})
            if drift:
                snapshot_drift = True
                drift_items = [f"{item.get('field', '?')}" for item in drift]
                issues.append({"file": "task_snapshot.yml", "issue": f"drift detected: {', '.join(drift_items[:5])}"})
        except Exception:
            pass

    pass_rate = artifacts_passed / max(artifacts_checked, 1)
    return {
        "valid": pass_rate >= 0.85 and not issues,
        "pass_rate": round(pass_rate, 2),
        "artifacts_checked": artifacts_checked,
        "artifacts_passed": artifacts_passed,
        "issues": issues,
        "issues_count": len(issues),
        "snapshot_drift": snapshot_drift,
    }


def has_execution_placeholder(content: str) -> bool:
    lowered = content.lower()
    for pattern in EXECUTION_PLACEHOLDER_PATTERNS:
        if pattern.lower() in lowered:
            return True
    if "planning phase" in lowered and any(
        marker in lowered
        for marker in ("commands run: none", "no command", "not executed", "not yet provided")
    ):
        return True
    return False


def has_shell_command_block_no_output(content: str) -> bool:
    """Detect reports that contain shell commands (e.g. in ```bash blocks) but
    no actual execution output or evidence.

    These are typically placeholder artifacts where the agent wrote a command
    it intended to run but never actually executed it.
    """
    # Extract content of ```bash or ```sh code blocks
    code_blocks = re.findall(r'```(?:bash|sh)\s*\n(.*?)```', content, re.DOTALL)
    if not code_blocks:
        # Also try bare code blocks that look like CLI commands
        code_blocks = re.findall(r'```\s*\n((?:(?:\$\s*)?(?:cd|ls|find|grep|cat|python|pip|npm|git|docker|curl|wget|make|cp|mv|rm|mkdir|echo|source|test|pytest|which|head|tail|sort|uniq|wc|diff)[^\n]*\n)+)```', content, re.DOTALL)

    if not code_blocks:
        return False

    # Check that all code blocks contain only commands — no output evidence
    has_output_evidence = False
    command_only_blocks = 0
    for block in code_blocks:
        lines = [l.strip() for l in block.strip().split('\n') if l.strip()]
        if not lines:
            continue
        # Check if this block looks like command lines only
        command_like = [
            l for l in lines
            if re.match(r'^(\$\s*)?(cd|ls|find|grep|cat|python|pip|npm|git|docker|curl|wget|make|cp|mv|rm|mkdir|echo|source|test|pytest|which|head|tail|sort|uniq|wc|diff|sed|awk|brew|apt|bundle|go|cargo|java|javac|npx|yarn|node|perl|ruby|ssh|scp|tar|zip|unzip|chmod|chown|export|set|unset|env)\b', l)
        ]
        if len(command_like) >= len(lines) * 0.7:
            command_only_blocks += 1
        # Check if any block has typical command output
        if any(re.match(r'^(#|//|/\*|-->|Error|error|WARNING|INFO|DEBUG|SUCCESS|FAIL|PASS|OK|Found|Total|Result|Output|exit|usage|Usage|Syntax)', l) for l in lines):
            has_output_evidence = True

    if command_only_blocks > 0 and not has_output_evidence:
        # Additional check: does the report have a "Commands run:" section at all?
        if "commands run:" not in content.lower():
            return True

    return False


def is_command_placeholder_artifact(fname: str, content: str) -> bool:
    """Check if a non-execution-required artifact is still just a command placeholder.
    
    This catches agents like RepoScout producing only shell command text without
    actual findings. These are treated as 'command placeholder' issues.
    """
    if fname in EXECUTION_REQUIRED_FILES:
        return False  # Already checked by has_execution_placeholder
    return has_shell_command_block_no_output(content)


def has_unexecuted_tool_call(content: str) -> bool:
    lowered = content.lower()
    if not any(pattern in lowered for pattern in UNEXECUTED_TOOL_CALL_PATTERNS):
        return False
    stripped = content.strip()
    if stripped.lower().startswith("<tool_call"):
        return True
    without_tool_xml = re.sub(r"<tool_call\b.*?</tool_call>", "", stripped, flags=re.IGNORECASE | re.DOTALL)
    return len(without_tool_xml.strip()) < 200


def has_archivist_placeholder(content: str) -> bool:
    lowered = content.lower()
    return any(pattern.lower() in lowered for pattern in ARCHIVIST_PLACEHOLDER_PATTERNS)


def claims_missing_user_decision_file(content: str, run_dir: Path | None = None) -> bool:
    lowered = content.lower()
    if "user_decision_required.md" not in lowered:
        return False
    if "no user_decision_required" in lowered or "no user decision required" in lowered:
        return False
    if not any(pattern in lowered for pattern in USER_DECISION_CLAIM_PATTERNS):
        return False
    if run_dir and (run_dir / "USER_DECISION_REQUIRED.md").exists():
        return False
    return True


def artifact_content_issues(fname: str, content: str, run_dir: Path | None = None) -> list[str]:
    """Return semantic content issues for one artifact.

    The checks intentionally stay conservative and pattern-based. They catch the
    recurring AgentLab failure mode where a node produced text, but that text was
    a tool request, a plan-only placeholder, or a claimed blocker artifact that
    was never actually written.
    """
    issues: list[str] = []
    if is_tbd_or_empty(content):
        issues.append("TBD or empty placeholder")
    if has_unexecuted_tool_call(content):
        issues.append("unexecuted tool call in report")
    if fname in EXECUTION_REQUIRED_FILES and has_execution_placeholder(content):
        issues.append("execution placeholder or no command evidence")
    if is_command_placeholder_artifact(fname, content):
        issues.append("command-only placeholder: shell commands present but no execution output or findings")
    if fname == "09_archive_update.md" and has_archivist_placeholder(content):
        issues.append("archivist memory update placeholder")
    if fname == "01_supervisor_plan.md" and claims_missing_user_decision_file(content, run_dir):
        issues.append("claims USER_DECISION_REQUIRED.md but file is missing")
    return issues


def artifact_content_is_valid(fname: str, content: str, run_dir: Path | None = None) -> bool:
    return not artifact_content_issues(fname, content, run_dir)


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
    from atomic_io import atomic_write_text
    atomic_write_text(path, yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
