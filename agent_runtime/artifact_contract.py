"""AgentLab Artifact Contract - rigorous artifact validation.

Detects missing files, TBD-only files, empty files, invalid YAML,
semantic placeholders, and ensures every lifecycle node has valid outputs.
"""

from __future__ import annotations

from pathlib import Path
import json
import re
import zipfile

import yaml

try:
    from agent_runtime.execution_log import load_execution_log, has_successful_command, get_command_by_id
except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
    from execution_log import load_execution_log, has_successful_command, get_command_by_id

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

PACK_METADATA_KEYS = {
    "schema_version",
    "version",
    "project",
    "task_id",
    "production_pack",
    "artifact",
    "status",
    "execution_mode",
    "generated_by",
    "candidate_only",
    "production_modified",
}

REQUIRED_ARTIFACTS_BY_ROUTE = {
    "user_request": ["user_request.md"],
    "workflow_plan": ["workflow_plan.yml"],
    "supervisor": ["01_supervisor_plan.md"],
    "reposcout": ["02_reposcout_report.md"],
    "researcher": ["03_research_notes.md"],
    "observer": ["observation_report.yml"],
    "interface_mapper": ["04_interface_map.md"],
    "coder": ["06_implementation_report.md"],
    "artifact_producer": ["artifact_producer_report.md"],
    "narrative_planner": ["chapter_state_plan.yml"],
    "tester_auditor": ["07_validation_report.md", "08_audit_report.md"],
    "verifier": ["verification_report.md"],
    "archivist": [
        "09_archive_update.md",
        "artifact_lineage.yml",
        "artifact_promotion_plan.yml",
        "archive_receipt.yml",
    ],
    "codex_prompt_generator": ["05_coder_prompt.md"],
    "self_check": ["self_check_report.yml"],
    "sync": ["sync_report.yml"],
    "finalize": ["task_card.yml", "artifact_manifest.yml"],
}

COMMON_ARTIFACTS = [
    "user_request.md", "workflow_plan.yml", "state.yml", "progress.yml",
    "task_snapshot.yml", "brain_decisions.yml", "cost_ledger.yml",
]

NODE_ARTIFACTS = {
    "REPO_CONTEXT": ["02_reposcout_report.md"],
    "RESEARCH_OPTIONAL": ["03_research_notes.md"],
    "OBSERVATION_OPTIONAL": ["observation_report.yml"],
    "INTERFACE_OPTIONAL": ["04_interface_map.md"],
    "NARRATIVE_REWRITE_PLAN": ["chapter_state_plan.yml"],
    "WRITER_DRAFT": ["fiction_draft.md"],
    "FICTION_REVIEW": ["fiction_review.yml"],
    "SCRIBE_LEDGER": ["continuity_ledger.yml"],
    "CODER_IMPLEMENTATION": ["06_implementation_report.md"],
    "ARTIFACT_PRODUCTION": ["artifact_producer_report.md"],
    "VISUAL_OBSERVATION": ["visual_observation_report.yml"],
    "VISUAL_REVIEW": ["visual_review_report.yml", "media_qc_report.yml"],
    "VALIDATION": ["07_validation_report.md"],
    "AUDIT": ["08_audit_report.md"],
    "VERIFY": ["verification_report.md"],
    "ARCHIVE": [
        "09_archive_update.md",
        "artifact_lineage.yml",
        "artifact_promotion_plan.yml",
        "archive_receipt.yml",
    ],
    "SYNC_OPTIONAL": ["sync_report.yml"],
}

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

    workflow_plan = _load_workflow_plan(run_dir)
    route = _route_from_workflow_plan(workflow_plan)
    all_artifact_names = _required_artifacts_for_run(run_dir, route, workflow_plan) + [
        "lifecycle.yml",
        "self_check_report.yml",
        "task_card.yml",
    ]
    all_artifact_names = list(dict.fromkeys(all_artifact_names))

    for fname in all_artifact_names:
        path = run_dir / fname
        artifacts_checked += 1

        if not path.exists():
            if _artifact_node_skipped(run_dir, fname):
                artifacts_passed += 1
                continue
            issues.append({"file": fname, "issue": "missing"})
            continue

        if path.is_dir():
            if any(child.is_file() for child in path.rglob("*")):
                artifacts_passed += 1
            else:
                issues.append({"file": fname, "issue": "empty directory"})
            continue

        binary_issue = _binary_artifact_format_issue(path)
        if binary_issue:
            issues.append({"file": fname, "issue": binary_issue})
            continue
        if path.suffix.lower() in {".xlsx", ".docx", ".pptx", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov"}:
            artifacts_passed += 1
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

    governance_issues = _project_artifact_governance_issues(run_dir)
    if governance_issues:
        issues.extend(
            {"file": "project_artifact_governance", "issue": issue}
            for issue in governance_issues
        )

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
    if (
        "commands run: none by this model call" in lowered
        and ("direct_api" in lowered or "direct api" in lowered or "direct api text-generation" in lowered)
        and (
            "agentlab_edit" in lowered
            or "candidate implementation" in lowered
            or "candidate-only" in lowered
            or "proposed validation commands" in lowered
        )
    ):
        return False
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


def has_unclosed_structured_edit_block(content: str) -> bool:
    html_starts = len(re.findall(r"<!--\s*AGENTLAB_EDIT\s*:", content, flags=re.IGNORECASE))
    html_complete = len(
        re.findall(
            r"<!--\s*AGENTLAB_EDIT\s*:\s*.+?-->\s*\n.*?\n\s*<!--\s*END\s+AGENTLAB_EDIT\s*-->",
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )
    if html_starts != html_complete:
        return True

    primary_starts = len(re.findall(r"<<<AGENTLAB_EDIT\b", content))
    primary_complete = len(
        re.findall(r"<<<AGENTLAB_EDIT\s+.+?\n.*?>>>", content, flags=re.DOTALL)
    )
    return primary_starts != primary_complete


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
    if has_unclosed_structured_edit_block(content):
        issues.append("unclosed structured edit block")
    pack_issue = _production_pack_placeholder_issue(fname, content, run_dir)
    if pack_issue:
        issues.append(pack_issue)

    # ── P1-1: execution evidence gate ──
    execution_evidence_issue = _check_execution_evidence(fname, content, run_dir)
    if execution_evidence_issue:
        issues.append(execution_evidence_issue)

    repo_evidence_issues = _check_repo_analysis_evidence(fname, content, run_dir)
    issues.extend(repo_evidence_issues)

    intelligence_issues = _check_search_repo_intelligence_evidence(fname, content, run_dir)
    issues.extend(intelligence_issues)

    return issues


def artifact_content_is_valid(fname: str, content: str, run_dir: Path | None = None) -> bool:
    return not artifact_content_issues(fname, content, run_dir)


def _production_pack_placeholder_issue(
    fname: str,
    content: str,
    run_dir: Path | None = None,
) -> str | None:
    if run_dir is None or not fname.endswith((".yml", ".yaml")):
        return None

    workflow_plan = _load_workflow_plan(run_dir)
    required_outputs = set(_production_pack_required_outputs(workflow_plan, run_dir))
    if fname not in required_outputs:
        return None

    try:
        data = yaml.safe_load(content) or {}
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    if (
        fname == "visual_acceptance_candidate.yml"
        and data.get("status") == "not_required"
        and data.get("candidates") == []
    ):
        return None

    if _has_meaningful_pack_payload(data):
        return None
    return "production-pack candidate artifact has no meaningful payload beyond metadata"


def _has_meaningful_pack_payload(data: dict) -> bool:
    for key, value in data.items():
        if key in PACK_METADATA_KEYS:
            continue
        if _value_has_meaningful_pack_content(value):
            return True
    return False


def _value_has_meaningful_pack_content(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_value_has_meaningful_pack_content(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_value_has_meaningful_pack_content(v) for v in value)
    if isinstance(value, bool):
        return value
    return True


def required_artifacts_for_route(route: list[str]) -> list[str]:
    """Determine required artifacts for a given agent route."""
    required = list(COMMON_ARTIFACTS)
    agent_map = {
        "Supervisor": "supervisor",
        "RepoScout": "reposcout",
        "Researcher": "researcher",
        "Observer": "observer",
        "InterfaceMapper": "interface_mapper",
        "Coder": "coder",
        "ArtifactProducer": "artifact_producer",
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


def _load_workflow_plan(run_dir: Path) -> dict:
    plan_path = run_dir / "workflow_plan.yml"
    if not plan_path.exists():
        return {}
    try:
        plan = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return plan if isinstance(plan, dict) else {}


def _load_route(run_dir: Path) -> list[str]:
    return _route_from_workflow_plan(_load_workflow_plan(run_dir))


def _route_from_workflow_plan(plan: dict) -> list[str]:
    if not isinstance(plan, dict):
        return []
    route = plan.get("route", {})
    if isinstance(route, dict):
        return list(route.get("agents", []) or [])
    if isinstance(route, list):
        return list(route)
    return []


def _required_artifacts_for_run(run_dir: Path, route: list[str], workflow_plan: dict) -> list[str]:
    required = required_artifacts_for_route(route)
    route_data = workflow_plan.get("route", {}) if isinstance(workflow_plan, dict) else {}
    route_key = route_data.get("route_key") if isinstance(route_data, dict) else None
    if route_key == "narrative_heavy_audit":
        required = [name for name in required if name != "verification_report.md"]
    required.extend(_route_required_outputs(workflow_plan))
    required.extend(_production_pack_required_outputs(workflow_plan, run_dir))
    required.extend(_artifact_task_required_outputs(run_dir))
    skipped_files = _skipped_lifecycle_artifacts(run_dir)
    return [name for name in required if name not in skipped_files]


def _artifact_task_required_outputs(run_dir: Path) -> list[str]:
    contract_path = run_dir / "artifact_task.yml"
    try:
        contract = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    validation = contract.get("validation") if isinstance(contract, dict) else {}
    raw_paths = (
        validation.get("required_paths")
        if isinstance(validation, dict)
        else []
    )
    if not isinstance(raw_paths, list):
        return []
    names: list[str] = []
    for raw in raw_paths:
        path = Path(str(raw))
        if path.is_absolute() or ".." in path.parts:
            continue
        if path.parts[:2] == ("runs", run_dir.name):
            path = Path(*path.parts[2:])
        elif path.parts[:1] == ("runs",):
            continue
        normalized = _normalize_run_artifact_name(path.as_posix())
        if normalized:
            names.append(normalized)
    return list(dict.fromkeys(names))


def _binary_artifact_format_issue(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix not in {
        ".xlsx", ".docx", ".pptx", ".pdf", ".png", ".jpg", ".jpeg",
        ".webp", ".mp4", ".mov",
    }:
        return None
    if path.stat().st_size <= 0:
        return "empty binary artifact"
    if suffix in {".xlsx", ".docx", ".pptx"}:
        if not zipfile.is_zipfile(path):
            return "invalid Office package"
        required_entry = {
            ".xlsx": "xl/workbook.xml",
            ".docx": "word/document.xml",
            ".pptx": "ppt/presentation.xml",
        }[suffix]
        try:
            with zipfile.ZipFile(path) as package:
                names = set(package.namelist())
        except (OSError, zipfile.BadZipFile):
            return "invalid Office package"
        if "[Content_Types].xml" not in names or required_entry not in names:
            return f"invalid Office package: missing {required_entry}"
        return None
    with path.open("rb") as stream:
        header = stream.read(12)
    if suffix == ".pdf" and header[:5] != b"%PDF-":
        return "invalid PDF signature"
    if suffix == ".png" and header[:8] != b"\x89PNG\r\n\x1a\n":
        return "invalid PNG signature"
    if suffix in {".jpg", ".jpeg"} and header[:3] != b"\xff\xd8\xff":
        return "invalid JPEG signature"
    if suffix == ".webp" and (header[:4] != b"RIFF" or header[8:12] != b"WEBP"):
        return "invalid WebP signature"
    if suffix in {".mp4", ".mov"} and header[4:8] != b"ftyp":
        return "invalid ISO media signature"
    return None


def validate_artifact_task_outputs(
    run_dir: Path,
    *,
    deferred_paths: set[str] | None = None,
) -> list[dict[str, str]]:
    """Validate exact ArtifactTask outputs before a role result can complete."""

    deferred = deferred_paths or set()
    issues: list[dict[str, str]] = []
    contract_path = run_dir / "artifact_task.yml"
    try:
        contract = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        contract = {}
    validation = contract.get("validation") if isinstance(contract, dict) else {}
    semantic_validator = (
        validation.get("semantic_validator")
        if isinstance(validation, dict)
        else None
    )
    for name in _artifact_task_required_outputs(run_dir):
        if name in deferred or Path(name).name in deferred:
            continue
        path = run_dir / name
        if not path.exists():
            issues.append({"file": name, "issue": "missing"})
            continue
        if path.is_dir():
            if not any(child.is_file() for child in path.rglob("*")):
                issues.append({"file": name, "issue": "empty directory"})
            continue
        binary_issue = _binary_artifact_format_issue(path)
        if binary_issue:
            issues.append({"file": name, "issue": binary_issue})
            continue
        if path.stat().st_size <= 0:
            issues.append({"file": name, "issue": "empty"})
            continue
        if path.suffix.lower() in {".yml", ".yaml"}:
            try:
                document = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
                issues.append({"file": name, "issue": f"invalid YAML: {exc}"})
                continue
            if semantic_validator == "fact_distillation":
                try:
                    from agent_runtime.project_reset import fact_distillation_issues
                except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
                    from project_reset import fact_distillation_issues
                assigned_inputs = contract.get("assigned_inputs") or []
                allowed_hashes = {
                    str(item.get("sha256") or "")
                    for item in assigned_inputs
                    if isinstance(item, dict) and item.get("sha256")
                }
                if not isinstance(document, dict):
                    semantic_issues = ["invalid_document"]
                else:
                    semantic_issues = fact_distillation_issues(
                        document,
                        allowed_source_hashes=allowed_hashes,
                    )
                    expected_sources = [
                        {
                            "path": str(item.get("project_path") or ""),
                            "sha256": str(item.get("sha256") or ""),
                        }
                        for item in assigned_inputs
                        if isinstance(item, dict)
                    ]
                    actual_sources = [
                        {
                            "path": str(item.get("path") or ""),
                            "sha256": str(item.get("sha256") or ""),
                        }
                        for item in document.get("sources") or []
                        if isinstance(item, dict)
                    ]
                    if actual_sources != expected_sources:
                        semantic_issues.append("source_contract_mismatch")
                issues.extend(
                    {"file": name, "issue": issue}
                    for issue in sorted(set(semantic_issues))
                )
    return issues


def _route_required_outputs(workflow_plan: dict) -> list[str]:
    route = workflow_plan.get("route", {}) if isinstance(workflow_plan, dict) else {}
    route_key = route.get("route_key") if isinstance(route, dict) else None
    if route_key == "narrative_batch_chapters":
        return [
            "chapter_batch_plan.yml",
            "chapters/chapter_001.md",
            "batch_continuity_ledger.yml",
            "state_transition_proposal.yml",
            "narrative_batch_delivery_receipt.yml",
        ]
    if route_key == "narrative_heavy_audit":
        return [
            "fiction_review.yml",
            "continuity_failure_report.yml",
            "state_transition_proposal.yml",
            "revision_or_rewrite_proposal.yml",
        ]
    if route_key == "narrative_rewrite_plan":
        return ["chapter_state_plan.yml"]
    return []


def _production_pack_required_outputs(workflow_plan: dict, run_dir: Path) -> list[str]:
    pack = workflow_plan.get("production_pack") if isinstance(workflow_plan, dict) else {}
    if not isinstance(pack, dict):
        return []
    outputs = pack.get("required_outputs")
    if not isinstance(outputs, list) or not outputs:
        return []
    if _lifecycle_node_status(run_dir, "ARTIFACT_PRODUCTION") == "skipped":
        return []
    names: list[str] = []
    for output in outputs:
        normalized = _normalize_run_artifact_name(str(output))
        if normalized:
            names.append(normalized)
    return names


def _normalize_run_artifact_name(raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None
    for prefix in ("runs/task_xxxx/", "runs/<task_id>/", "./"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        return None
    return path.as_posix()


def _skipped_lifecycle_artifacts(run_dir: Path) -> set[str]:
    skipped: set[str] = set()
    for node_id, files in NODE_ARTIFACTS.items():
        if _lifecycle_node_status(run_dir, node_id) == "skipped":
            skipped.update(files)
    return skipped


def _artifact_node_skipped(run_dir: Path, fname: str) -> bool:
    for node_id, files in NODE_ARTIFACTS.items():
        if fname in files and _lifecycle_node_status(run_dir, node_id) == "skipped":
            return True
    return False


def _lifecycle_node_status(run_dir: Path, node_id: str) -> str | None:
    try:
        from lifecycle_graph import load_lifecycle
    except ModuleNotFoundError:  # pragma: no cover - package import path
        from agent_runtime.lifecycle_graph import load_lifecycle
    lifecycle = load_lifecycle(run_dir) or {}
    if not isinstance(lifecycle, dict):
        return None
    node = (lifecycle.get("nodes") or {}).get(node_id) or {}
    return node.get("status") if isinstance(node, dict) else None


def _project_artifact_governance_issues(run_dir: Path) -> list[str]:
    if run_dir.parent.name != "runs":
        return []
    project_root = run_dir.parent.parent
    if project_root.parent.name != "projects":
        return []
    agentlab_root = project_root.parent.parent
    try:
        try:
            from agent_runtime.project_artifact_steward import validate_project_artifact_governance
        except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
            from project_artifact_steward import validate_project_artifact_governance

        return validate_project_artifact_governance(
            agentlab_root,
            project_root.name,
            run_dir.name,
            run_dir=run_dir,
        )
    except Exception as exc:
        return [f"Project Artifact Steward validation failed: {type(exc).__name__}: {exc}"]


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
    try:
        from agent_runtime.atomic_io import atomic_write_text
    except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
        from atomic_io import atomic_write_text

    atomic_write_text(path, yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _check_execution_evidence(fname: str, content: str, run_dir: Path | None = None) -> str | None:
    """Check if a validation/audit report claims command execution
    but does not reference an execution_log command_id.

    Also cross-references exit_code: if a report claims success but the
    referenced command has non-zero exit_code, the evidence is invalid.
    """
    # Only apply to validation/audit/verification reports
    evidence_report_files = {
        "07_validation_report.md",
        "08_audit_report.md",
        "verification_report.md",
    }
    if fname not in evidence_report_files:
        return None

    lowered = content.lower()

    # Look for command execution claims (spec-driven trigger list)
    command_claim_patterns = [
        "commands run", "command run",
        "pytest", "python -m pytest",
        "npm test", "pnpm test", "yarn test",
        "cmake", "make", "xcodebuild",
        "cargo test", "go test",
        "exit code", "exit_code",
        "passed", "all tests passed", "tests passed",
        "build passed", "validation passed",
        "ran ", "executed", "test results",
    ]
    has_command_claim = any(p in lowered for p in command_claim_patterns)
    if not has_command_claim:
        return None

    # Native CLI workers may preserve their report verbatim while the executor
    # writes command provenance to a role-specific companion capture. Treat the
    # pair as one evidence envelope, but still require an id that exists in the
    # authoritative execution log.
    evidence_content = content
    has_command_id = (
        "command_id" in lowered
        or "cmd_" in lowered
        or "execution_log" in lowered
        or "evidence:" in lowered
    )
    if not has_command_id and run_dir is not None:
        capture_name = {
            "07_validation_report.md": "testerauditor_cli_result_capture.md",
            "08_audit_report.md": "testerauditor_cli_result_capture.md",
            "verification_report.md": "verifier_cli_result_capture.md",
        }[fname]
        capture_path = run_dir / capture_name
        if capture_path.is_file():
            capture = capture_path.read_text(encoding="utf-8", errors="replace")
            capture_lowered = capture.lower()
            if any(
                marker in capture_lowered
                for marker in ("command_id", "cmd_", "execution_log", "evidence:")
            ):
                evidence_content = f"{content}\n{capture}"
                has_command_id = True
    if not has_command_id:
        # Report claims command execution but does not reference command_id
        return (
            "Report claims command execution but does not reference execution_log command_id. "
            "Add 'command_id: cmd_XXXX' or 'Evidence:' section linking to execution_log.yml."
        )

    # ── command_id referenced – verify against execution_log ──
    if run_dir is None:
        return None

    log = load_execution_log(run_dir)
    commands = log.get("commands", [])
    if not commands:
        return "Report references command_id but execution_log.yml is missing or has no commands."

    # Find the first command_id mentioned in the report that exists in the log
    command_ids = [cmd.get("command_id", "") for cmd in commands]
    matched_cid: str | None = None
    for cid in command_ids:
        if cid and cid in evidence_content:
            matched_cid = cid
            break

    if matched_cid is None:
        return (
            "Report references command_id but no matching command_id found in execution_log.yml. "
            "Ensure the command_id in the report matches a record in execution_log.yml."
        )

    # ── exit_code cross-check ──
    # If the report claims success/passed, the referenced command must have exit_code == 0.
    success_claim_patterns = [
        "passed", "all tests passed", "tests passed",
        "build passed", "validation passed",
        "success", "successful",
    ]
    claims_success = any(p in lowered for p in success_claim_patterns)
    if claims_success:
        cmd = get_command_by_id(run_dir, matched_cid)
        if cmd is not None and cmd.get("exit_code") != 0:
            return (
                f"Report claims success but command_id {matched_cid} has non-zero exit_code "
                f"({cmd.get('exit_code')})."
            )

    return None


def _load_repo_manifest(run_dir: Path | None) -> dict:
    if run_dir is None:
        return {}
    path = run_dir / "repo_manifest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _manifest_paths(run_dir: Path | None) -> list[Path]:
    if run_dir is None:
        return []
    paths: list[Path] = []
    if (run_dir / "repo_manifest.json").exists():
        paths.append(run_dir / "repo_manifest.json")
    manifests_dir = run_dir / "repo_manifests"
    if manifests_dir.exists():
        paths.extend(sorted(manifests_dir.glob("*.json")))
    return paths


def _load_all_repo_manifests(run_dir: Path | None) -> list[dict]:
    manifests = []
    for path in _manifest_paths(run_dir):
        try:
            manifests.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return manifests


def _load_resource_ledger(run_dir: Path | None) -> dict:
    if run_dir is None:
        return {}
    path = run_dir / "resource_ledger.yml"
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _load_yaml_artifact(run_dir: Path | None, relative_path: str) -> dict:
    if run_dir is None:
        return {}
    candidates = [run_dir / relative_path, run_dir / "artifacts" / "search" / relative_path, run_dir / "artifacts" / "repo_index" / relative_path]
    for path in candidates:
        if path.exists():
            try:
                return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception:
                return {}
    return {}


def _json_artifact_exists(run_dir: Path | None, relative_path: str, subdir: str) -> bool:
    if run_dir is None:
        return False
    return (run_dir / relative_path).exists() or (run_dir / "artifacts" / subdir / relative_path).exists()


def _check_search_repo_intelligence_evidence(fname: str, content: str, run_dir: Path | None = None) -> list[str]:
    evidence_report_files = {
        "02_reposcout_report.md",
        "03_research_notes.md",
        "04_interface_map.md",
        "06_implementation_report.md",
        "07_validation_report.md",
        "08_audit_report.md",
        "verification_report.md",
    }
    if fname not in evidence_report_files:
        return []
    lowered = content.lower()
    if "planned but skipped" in lowered or "planned/skipped" in lowered:
        return []
    issues: list[str] = []

    search_ledger = _load_yaml_artifact(run_dir, "search_ledger.yml")
    search_results_exists = _json_artifact_exists(run_dir, "search_results.json", "search")
    search_entries = search_ledger.get("entries") or []
    if any(p in lowered for p in ["searched web", "web search", "搜索了", "used anysearch", "extracted url"]):
        if not search_ledger or not search_results_exists:
            issues.append("Report claims search/URL extraction but search_ledger.yml and search_results.json evidence are missing.")
    if "used anysearch" in lowered and not any(e.get("provider") == "anysearch" for e in search_entries if isinstance(e, dict)):
        issues.append("Report claims AnySearch use but search_ledger provider=anysearch evidence is missing.")
    if "extracted url" in lowered and not any(e.get("action") == "url_extract" for e in search_entries if isinstance(e, dict)):
        issues.append("Report claims URL extraction but search_ledger action=url_extract evidence is missing.")

    repo_ledger = _load_yaml_artifact(run_dir, "repo_index_ledger.yml")
    semantic_exists = _json_artifact_exists(run_dir, "repo_semantic_library.json", "repo_index")
    if "indexed repo" in lowered:
        if not repo_ledger or not (repo_ledger.get("index") or {}).get("performed"):
            issues.append("Report claims repo indexing but repo_index_ledger.yml index.performed=true evidence is missing.")
    if "queried codegraph" in lowered and not (repo_ledger.get("queries") or []):
        issues.append("Report claims CodeGraph query but repo_index_ledger queries evidence is missing.")
    if "used code graph" in lowered or "used codegraph" in lowered:
        if not semantic_exists:
            issues.append("Report claims code graph use but repo_semantic_library.json evidence is missing.")
    return issues


def _check_repo_analysis_evidence(fname: str, content: str, run_dir: Path | None = None) -> list[str]:
    """Check repository-analysis claims against repo/resource/command evidence."""
    evidence_report_files = {
        "02_reposcout_report.md",
        "03_research_notes.md",
        "04_interface_map.md",
        "06_implementation_report.md",
        "07_validation_report.md",
        "08_audit_report.md",
        "verification_report.md",
    }
    if fname not in evidence_report_files:
        return []
    lowered = content.lower()
    issues: list[str] = []

    repo_claims = [
        "analyzed the repository",
        "analyzed repository",
        "analyzed repo",
        "analysed the repository",
        "analysed repository",
        "repository review",
        "repo analysis",
        "分析了仓库",
        "读取了仓库",
        "read repository",
    ]
    file_claims = re.findall(
        r"(?:read|loaded|inspected|读取了)\s+[`'\"]?([A-Za-z0-9_./-]+\.[A-Za-z0-9_+-]+)",
        content,
        flags=re.IGNORECASE,
    )
    clone_claim = any(pattern in lowered for pattern in ["git clone", "cloned the repo", "cloned repository", "clone 了仓库"])
    command_claim = any(pattern in lowered for pattern in ["executed command", "ran command", "command executed"])
    build_claim = any(pattern in lowered for pattern in ["ran tests", "ran build", "跑了测试", "跑了构建", "cmake --build", "npm test", "pytest"])

    manifests = _load_all_repo_manifests(run_dir)
    has_repo_manifest = bool(manifests)
    if not has_repo_manifest:
        manifests = [
            {
                "repo_url": "mock",
                "owner": "saintpeter",
                "repo": "Crown_of_Ash",
                "files_read": [{"path": path} for path in file_claims],
                "files_skipped_by_policy": [],
            }
        ]
    manifest = manifests[0]
    resource_ledger = _load_resource_ledger(run_dir)

    if any(pattern in lowered for pattern in repo_claims) and not has_repo_manifest:
        issues.append("Report claims repository analysis but repo_manifest.json is missing.")

    if file_claims:
        files_read = []
        files_skipped = []
        for item_manifest in manifests:
            files_read.extend(item.get("path") for item in (item_manifest.get("files_read") or []) if isinstance(item, dict))
            files_skipped.extend(item.get("path") for item in (item_manifest.get("files_skipped_by_policy") or []) if isinstance(item, dict))
        for claimed_path in file_claims:
            claimed_path = claimed_path.rstrip(".,;:")
            if claimed_path.lower() in {"repo_manifest.json", "resource_ledger.yml", "execution_log.yml"}:
                continue
            if "based on api manifest" in lowered and claimed_path == "repo_manifest.json":
                continue
            if claimed_path in files_skipped:
                continue
            if not has_repo_manifest:
                issues.append("Report claims file reads but repo_manifest.json is missing.")
            elif claimed_path not in files_read:
                issues.append(f"Report claims file read without repo_manifest evidence: {claimed_path}")

    if any(pattern in lowered for pattern in ["skipped file", "skipped "]):
        skipped_claims = re.findall(r"(?:skipped|跳过)\s+[`'\"]?([A-Za-z0-9_./-]+\.[A-Za-z0-9_+-]+)", content, flags=re.IGNORECASE)
        files_skipped = []
        for item_manifest in manifests:
            files_skipped.extend(item.get("path") for item in (item_manifest.get("files_skipped_by_policy") or []) if isinstance(item, dict))
        for claimed_path in skipped_claims:
            claimed_path = claimed_path.rstrip(".,;:")
            if not has_repo_manifest:
                issues.append("Report claims skipped files but repo_manifest.json is missing.")
            elif claimed_path not in files_skipped:
                issues.append(f"Report claims skipped file without repo_manifest evidence: {claimed_path}")

    if clone_claim:
        access = resource_ledger.get("repo_access", {}) if isinstance(resource_ledger, dict) else {}
        if not resource_ledger:
            issues.append("Report claims clone activity but resource_ledger.yml is missing.")
        elif not access.get("clone_performed") and not access.get("sparse_clone_performed") and not access.get("full_clone_performed"):
            issues.append("Report claims clone activity but resource_ledger.yml shows no clone.")

    if command_claim or build_claim:
        log = load_execution_log(run_dir) if run_dir else {}
        if not log.get("commands"):
            issues.append("Report claims command/build/test execution but execution_log.yml is missing or empty.")

    return issues
