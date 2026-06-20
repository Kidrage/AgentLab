#!/usr/bin/env python3
"""Check GitHub raw text integrity for critical AgentLab files."""

from __future__ import annotations

# text-integrity: keep this file as real physical lines in Git and GitHub raw.
import argparse
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from time import time_ns
from urllib.parse import quote

CRITICAL_FILES = [
    ".github/workflows/ci.yml",
    "agent_runtime/skill_distiller.py",
    "agent_runtime/skill_vault.py",
    "agent_runtime/skill_backup.py",
    "agent_runtime/post_task_learning.py",
    "agent_runtime/external_skill_importer.py",
    "agent_runtime/pipeline_runner.py",
    "agent_runtime/search_cli.py",
    "agent_runtime/search/provider.py",
    "agent_runtime/search/policy.py",
    "agent_runtime/skill_evolution.py",
    "config/skill_distillation.yml",
    "config/skill_vault.yml",
    "config/backup_policy.yml",
    "config/search_providers.yml",
    "config/external_skill_import_policy.yml",
    "docs/SKILL_DISTILLATION.md",
    "docs/SKILL_DISCOVERY_ROADMAP.md",
    "docs/SKILL_VAULT.md",
    "scripts/audit_text_integrity.py",
    "scripts/check_remote_raw_integrity.py",
    "tests/test_repository_text_integrity.py",
    "tests/test_text_integrity_audit.py",
    "README.md",
    "agentlab.sh",
    # P2-L: Recovery closure feedback
    "agent_runtime/recovery/closure_feedback.py",
    "tests/test_p2_l_closure_feedback.py",
    # S6: Recovery Brain / alternative route planning
    "agent_runtime/recovery/failure_taxonomy.py",
    "agent_runtime/recovery/strategy_search.py",
    "agent_runtime/recovery/alternative_route_planner.py",
    "agent_runtime/recovery/capability_gap_resolver.py",
    "agent_runtime/recovery/escalation_policy.py",
    "agent_runtime/recovery/fake_evidence_detector.py",
    "config/recovery_strategy_policy.yml",
    "config/failure_taxonomy.yml",
    "config/evidence_integrity_policy.yml",
    "docs/S6_RECOVERY_BRAIN.md",
    "tests/test_s6_recovery_brain.py",
    "acceptance_runs/s6_recovery_brain/S6_RECOVERY_BRAIN_REPORT.md",
    "acceptance_runs/s6_recovery_brain/recovery_strategy_plan.yml",
    "acceptance_runs/s6_recovery_brain/alternative_route_plan.yml",
    "acceptance_runs/s6_recovery_brain/capability_gap_decision_card.yml",
    "acceptance_runs/s6_recovery_brain/fake_evidence_report.yml",
    "acceptance_runs/s6_recovery_brain/phase_acceptance_evidence.yml",
    "acceptance_runs/s6_recovery_brain/recovery_strategy_ledger.yml",
    # M1 Core Modules
    "agent_runtime/brain/mission_contract.py",
    "agent_runtime/brain/renderer.py",
    "agent_runtime/brain/project_type_classifier.py",
    "agent_runtime/brain/decision_card_builder.py",
    "agent_runtime/brain/risk_classifier.py",
    "agent_runtime/brain/acceptance_gate_builder.py",
    "agent_runtime/brain/artifact_contract_builder.py",
    "agent_runtime/brain/domain_classifier.py",
    "agent_runtime/brain/capability_requirement_builder.py",
    "agent_runtime/program_manager/project_brain.py",
    "agent_runtime/program_manager/context_compressor.py",
    "agent_runtime/program_manager/phase_acceptance.py",
    "agent_runtime/program_manager/acceptance_renderer.py",
    "agent_runtime/program_manager/next_action_decider.py",
    "agent_runtime/program_manager/phase_planner.py",
    "agent_runtime/project_workflows/planner.py",
    "agent_runtime/project_workflows/renderer.py",
    "agent_runtime/external_projects/models.py",
    "agent_runtime/external_projects/registry.py",
    # Hybrid Agent Executor and Workspace rules
    "AGENTS.md",
    "OPERATING_MODEL.md",
    "config/agent_model_profiles.yml",
    "agent_templates/coder.md",
    "agent_templates/supervisor.md",
    "agent_runtime/cli_executor.py",
    "agent_runtime/agent_runner.py",
    "tests/test_cli_executor.py",
]

MIN_LINES = {
    ".github/workflows/ci.yml": 20,
    "agent_runtime/skill_distiller.py": 200,
    "agent_runtime/skill_vault.py": 200,
    "agent_runtime/skill_backup.py": 100,
    "config/skill_vault.yml": 20,
    "config/backup_policy.yml": 200,
    "docs/SKILL_VAULT.md": 40,
    "scripts/audit_text_integrity.py": 120,
    "scripts/check_remote_raw_integrity.py": 80,
    "tests/test_repository_text_integrity.py": 80,
    "tests/test_text_integrity_audit.py": 60,
    "agentlab.sh": 20,
    # P2-L: Recovery closure feedback
    "agent_runtime/recovery/closure_feedback.py": 80,
    "tests/test_p2_l_closure_feedback.py": 80,
    # S6: Recovery Brain / alternative route planning
    "agent_runtime/recovery/failure_taxonomy.py": 80,
    "agent_runtime/recovery/strategy_search.py": 80,
    "agent_runtime/recovery/alternative_route_planner.py": 120,
    "agent_runtime/recovery/capability_gap_resolver.py": 80,
    "agent_runtime/recovery/escalation_policy.py": 80,
    "agent_runtime/recovery/fake_evidence_detector.py": 80,
    "config/recovery_strategy_policy.yml": 20,
    "config/failure_taxonomy.yml": 20,
    "config/evidence_integrity_policy.yml": 15,
    "docs/S6_RECOVERY_BRAIN.md": 40,
    "tests/test_s6_recovery_brain.py": 80,
    "acceptance_runs/s6_recovery_brain/S6_RECOVERY_BRAIN_REPORT.md": 40,
    "acceptance_runs/s6_recovery_brain/recovery_strategy_plan.yml": 10,
    "acceptance_runs/s6_recovery_brain/alternative_route_plan.yml": 5,
    "acceptance_runs/s6_recovery_brain/capability_gap_decision_card.yml": 10,
    "acceptance_runs/s6_recovery_brain/fake_evidence_report.yml": 5,
    "acceptance_runs/s6_recovery_brain/phase_acceptance_evidence.yml": 5,
    "acceptance_runs/s6_recovery_brain/recovery_strategy_ledger.yml": 5,
    # M1 Core Modules
    "agent_runtime/brain/mission_contract.py": 150,
    "agent_runtime/program_manager/project_brain.py": 100,
    "agent_runtime/brain/renderer.py": 80,
    "agent_runtime/project_workflows/planner.py": 80,
    "agent_runtime/program_manager/context_compressor.py": 80,
    "agent_runtime/program_manager/phase_acceptance.py": 80,
    "agent_runtime/program_manager/acceptance_renderer.py": 70,
    "agent_runtime/external_projects/models.py": 70,
    "agent_runtime/brain/decision_card_builder.py": 70,
    "agent_runtime/brain/project_type_classifier.py": 70,
    "agent_runtime/external_projects/registry.py": 60,
    "agent_runtime/program_manager/next_action_decider.py": 40,
    "agent_runtime/brain/artifact_contract_builder.py": 40,
    "agent_runtime/brain/risk_classifier.py": 40,
    "agent_runtime/brain/acceptance_gate_builder.py": 40,
    "agent_runtime/project_workflows/renderer.py": 40,
    "agent_runtime/brain/domain_classifier.py": 40,
    "agent_runtime/program_manager/phase_planner.py": 35,
    "agent_runtime/brain/capability_requirement_builder.py": 30,
    # Hybrid Agent Executor and Workspace rules
    "AGENTS.md": 80,
    "OPERATING_MODEL.md": 150,
    "config/agent_model_profiles.yml": 100,
    "agent_templates/coder.md": 100,
    "agent_templates/supervisor.md": 150,
    "agent_runtime/cli_executor.py": 120,
    "agent_runtime/agent_runner.py": 120,
    "tests/test_cli_executor.py": 100,
}

HIDDEN_LINE_SEPARATORS = {
    "\u0085": "U+0085 NEXT LINE",
    "\u2028": "U+2028 LINE SEPARATOR",
    "\u2029": "U+2029 PARAGRAPH SEPARATOR",
}

BIDI_CONTROL_CHARS = {
    "\u061c": "U+061C ARABIC LETTER MARK",
    "\u200e": "U+200E LEFT-TO-RIGHT MARK",
    "\u200f": "U+200F RIGHT-TO-LEFT MARK",
    "\u202a": "U+202A LEFT-TO-RIGHT EMBEDDING",
    "\u202b": "U+202B RIGHT-TO-LEFT EMBEDDING",
    "\u202c": "U+202C POP DIRECTIONAL FORMATTING",
    "\u202d": "U+202D LEFT-TO-RIGHT OVERRIDE",
    "\u202e": "U+202E RIGHT-TO-LEFT OVERRIDE",
    "\u2066": "U+2066 LEFT-TO-RIGHT ISOLATE",
    "\u2067": "U+2067 RIGHT-TO-LEFT ISOLATE",
    "\u2068": "U+2068 FIRST STRONG ISOLATE",
    "\u2069": "U+2069 POP DIRECTIONAL ISOLATE",
}


@dataclass
class RawResult:
    path: str
    status: str
    lines: int = 0
    max_line: int = 0
    bytes: int = 0
    issue: str = ""


def physical_lf_line_count(data: bytes) -> int:
    """Count physical LF-delimited lines, not Unicode splitlines."""
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def hidden_unicode_issues(text: str) -> list[str]:
    issues: list[str] = []
    for char, label in HIDDEN_LINE_SEPARATORS.items():
        if char in text:
            issues.append(f"contains hidden line separator {label}")
    for char, label in BIDI_CONTROL_CHARS.items():
        if char in text:
            issues.append(f"contains bidi control {label}")
    return issues


def fetch_raw(repo: str, branch: str, path: str, timeout: int = 20) -> RawResult:
    encoded_path = quote(path, safe="/")
    cache_bust = time_ns()
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/{encoded_path}?cache_bust={cache_bust}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        return RawResult(path=path, status=str(exc.code), issue=f"HTTP {exc.code}")
    except urllib.error.URLError as exc:
        return RawResult(path=path, status="ERROR", issue=str(exc.reason))
    text = data.decode("utf-8", errors="replace")
    physical_lines = physical_lf_line_count(data)
    lines = text.split("\n")
    max_line = max((len(line.rstrip("\r")) for line in lines), default=0)
    issues = hidden_unicode_issues(text)
    if len(data) > 1000 and physical_lines <= 10:
        issues.append(f"compressed: {physical_lines} physical LF lines for {len(data)} bytes")
    if max_line > 1000:
        issues.append(f"max line {max_line} > 1000")
    minimum = MIN_LINES.get(path)
    if minimum is not None and physical_lines < minimum:
        issues.append(f"critical file needs >= {minimum} LF lines, has {physical_lines}")
    return RawResult(
        path=path,
        status="OK" if not issues else "SUSPICIOUS",
        lines=physical_lines,
        max_line=max_line,
        bytes=len(data),
        issue="; ".join(issues),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check GitHub raw integrity for AgentLab critical files")
    parser.add_argument("--repo", required=True, help="owner/repo, e.g. Kidrage/AgentLab")
    parser.add_argument(
        "--branch",
        "--ref",
        dest="branch",
        default="main",
        help="Git branch or ref to check",
    )
    parser.add_argument("--fail-on-suspicious", action="store_true")
    parser.add_argument("paths", nargs="*", help="Optional paths to check instead of default critical files")
    args = parser.parse_args(argv)

    paths = args.paths or CRITICAL_FILES
    results = [fetch_raw(args.repo, args.branch, path) for path in paths]
    suspicious = [r for r in results if r.status != "OK"]
    print(f"Remote raw integrity: repo={args.repo} branch={args.branch}")
    print("Path | Status | Lines | Max Line | Bytes | Issue")
    print("--- | --- | ---: | ---: | ---: | ---")
    for result in results:
        print(
            f"{result.path} | {result.status} | {result.lines} | "
            f"{result.max_line} | {result.bytes} | {result.issue}"
        )
    print(f"Checked {len(results)} files; suspicious={len(suspicious)}")
    if suspicious and args.fail_on_suspicious:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
