#!/usr/bin/env python3
"""Audit repository text integrity for compressed Python/YAML/CI files.

The script is read-only for source/config files. It writes audit reports under
``acceptance_runs/stabilization`` so CI and reviewers can inspect suspected
text-compression regressions without mutating the codebase.
"""

from __future__ import annotations

# text-integrity: keep this file as real physical lines in Git and GitHub raw.
import argparse
import ast
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "acceptance_runs" / "stabilization"

SCAN_PATTERNS = [
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    "agent_runtime/**/*.py",
    "scripts/*.py",
    "scripts/*.sh",
    "tests/*.py",
    "config/*.yml",
    "config/*.yaml",
    "acceptance_runs/**/*.yml",
    "acceptance_runs/**/*.yaml",
    "acceptance_runs/**/*.md",
    "docs/*.md",
    "docs/**/*.md",
    "README.md",
    "agentlab.sh",
    "*.sh",
]

# Patterns to exclude from scanning (third-party, venv, etc.)
EXCLUDE_PATTERNS = [
    "**/.venv/**",
    "**/site-packages/**",
    "**/__pycache__/**",
]

# Files that legitimately contain local absolute paths (user-specific configs).
# The local-path check is suppressed ONLY for these explicitly-audited files.
# acceptance_runs/ reports must NOT contain raw /Users paths — sanitize before committing.
_SKIP_LOCAL_PATH_CHECK: set[str] = {
    "config/shared_agent_directory.yml",
}

# No blanket directory exemptions. Add individual files to _SKIP_LOCAL_PATH_CHECK
# only after verifying they cannot reasonably be sanitized.
_SKIP_LOCAL_PATH_DIRS: list[str] = []


def _is_exempt_from_local_path_check(rel: str) -> bool:
    """Return True if the file should skip the local-path check."""
    if rel in _SKIP_LOCAL_PATH_CHECK:
        return True
    for d in _SKIP_LOCAL_PATH_DIRS:
        if rel.startswith(d):
            return True
    return False

# Minimum line counts for critical files. Keep this list for real compressed
# artifacts; do not add small compatibility modules that would need padding.
MIN_LINE_COUNTS = {
    "config/approval_policy.yml": 10,
    "config/cost_policy_v2.yml": 10,
    "config/executor_cost_profiles.yml": 10,
    "config/model_cost_profiles.yml": 10,
    "config/worker_cost_profiles.yml": 10,
    "acceptance_runs/m2_cost_risk_approval/M2_6_ACCEPTANCE.md": 40,
    ".github/workflows/ci.yml": 20,
    "agent_runtime/mcp_server.py": 80,
    "agent_runtime/skills/registry.py": 80,
    "agent_runtime/skills/usage_ledger.py": 40,
    "agent_runtime/skills/incubation.py": 60,
    "agent_runtime/external_agents/ecc_inventory.py": 80,
    "agent_runtime/external_agents/handoff.py": 80,
    "agent_runtime/search/anysearch_adapter.py": 80,
    "agent_runtime/search/local_url_reader.py": 40,
    "agent_runtime/ingestion/repo_indexers/codegraph_adapter.py": 80,
    "agent_runtime/repo_index_cli.py": 60,
    "agent_runtime/governance/performance.py": 50,
    "agent_runtime/governance/cost.py": 50,
    "agent_runtime/governance/routing_feedback.py": 30,
    "agent_runtime/p2_closure/closure_runner.py": 80,
    "agent_runtime/run_task.py": 80,
    "agent_runtime/post_task_learning.py": 100,
    "agent_runtime/external_skill_importer.py": 120,
    "agent_runtime/pipeline_runner.py": 120,
    "agent_runtime/search_cli.py": 80,
    "agent_runtime/search/provider.py": 40,
    "agent_runtime/search/policy.py": 40,
    "agent_runtime/skill_evolution.py": 300,
    "agent_runtime/skill_distiller.py": 200,
    "agent_runtime/skill_vault.py": 200,
    "agent_runtime/skill_backup.py": 100,
    "config/search_providers.yml": 10,
    "config/external_skill_import_policy.yml": 10,
    "config/skill_distillation.yml": 20,
    "config/skill_discovery.yml": 10,
    "config/backup_policy.yml": 200,
    "config/skill_vault.yml": 20,
    "README.md": 20,
    "docs/SKILL_DISTILLATION.md": 20,
    "docs/SKILL_DISCOVERY_ROADMAP.md": 20,
    "docs/SKILL_VAULT.md": 40,
    "scripts/p2_provider_governance_check.py": 60,
    "scripts/audit_text_integrity.py": 120,
    "tests/test_repository_text_integrity.py": 80,
    "tests/test_text_integrity_audit.py": 60,
    "tests/test_p2_closure.py": 80,
    "agentlab.sh": 20,
    # P2-L: Recovery closure feedback
    "agent_runtime/recovery/closure_feedback.py": 80,
    "tests/test_p2_l_closure_feedback.py": 80,
    "docs/P2_L_CLOSURE_FEEDBACK.md": 20,
    # R0: Additional recovery files
    "agent_runtime/recovery/closure.py": 80,
    "agent_runtime/recovery/human_review.py": 80,
    "agent_runtime/recovery/redaction.py": 80,
    "agent_runtime/recovery/resume_policy.py": 80,
    "agent_runtime/recovery/retry_ledger.py": 80,
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


@dataclass
class FileAudit:
    """Result of auditing a single file."""
    path: str
    line_count: int
    max_line_length: int
    file_size_bytes: int
    suspicious_single_line: bool
    python_ast_ok: bool | None
    yaml_parse_ok: bool | None
    contains_docstring_future_same_line: bool
    contains_multiple_top_level_defs_one_line: bool
    issue_summary: str
    future_import_after_code: bool = False
    suspicious_literal_newlines: bool = False
    contains_hidden_line_separator: bool = False
    contains_bidi_control: bool = False


# Directories to always exclude from scanning
EXCLUDED_DIR_PARTS = {".venv", ".git", ".pytest_cache", "site-packages", "__pycache__", "node_modules", "dist", "build", "htmlcov", ".mypy_cache", ".ruff_cache"}
LOCAL_ABSOLUTE_PATH_RE = re.compile("/" + "Users" + r"/[^\s`'\"<>]+")
MAX_SOURCE_LINE_LENGTH = 1000
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


def _physical_lf_lines(content: str) -> list[str]:
    """Return LF-delimited physical lines, preserving hidden separators."""
    if not content:
        return []
    lines = content.split("\n")
    if content.endswith("\n"):
        lines = lines[:-1]
    return [line.rstrip("\r") for line in lines]


def _hidden_unicode_issues(content: str) -> tuple[list[str], bool, bool]:
    issues: list[str] = []
    has_hidden_line_separator = False
    has_bidi_control = False
    for char, label in HIDDEN_LINE_SEPARATORS.items():
        if char in content:
            has_hidden_line_separator = True
            issues.append(f"contains hidden line separator {label}")
    for char, label in BIDI_CONTROL_CHARS.items():
        if char in content:
            has_bidi_control = True
            issues.append(f"contains bidi control {label}")
    return issues, has_hidden_line_separator, has_bidi_control


def _resolve_scan_paths(root: Path) -> list[Path]:
    """Resolve all scan patterns into a deduplicated list of file paths,
    excluding third-party/vendor directories."""
    seen: dict[str, Path] = {}
    for pattern in SCAN_PATTERNS:
        for matched in sorted(root.glob(pattern)):
            if matched.is_file():
                rel = str(matched.relative_to(root))
                # Skip files inside excluded directories
                if any(part in EXCLUDED_DIR_PARTS for part in matched.parts):
                    continue
                if rel not in seen:
                    seen[rel] = matched
    return list(seen.values())


def _check_python(path: Path, root: Path) -> FileAudit:
    """Run Python-specific integrity checks."""
    rel = str(path.relative_to(root))
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = _physical_lf_lines(content)
    size = path.stat().st_size
    line_count = len(lines)
    issues: list[str] = []
    suspicious = False
    hidden_issues, has_hidden_line_separator, has_bidi_control = _hidden_unicode_issues(content)
    if hidden_issues:
        suspicious = True
        issues.extend(hidden_issues)

    # AST parse
    ast_ok: bool | None = None
    try:
        ast.parse(content)
        ast_ok = True
    except SyntaxError as exc:
        ast_ok = False
        issues.append(f"ast.parse failed: {exc}")
    except Exception as exc:
        ast_ok = False
        issues.append(f"ast error: {exc}")

    max_line_len = max((len(line) for line in lines), default=0)
    if max_line_len > MAX_SOURCE_LINE_LENGTH:
        suspicious = True
        issues.append(f"max line length {max_line_len} > {MAX_SOURCE_LINE_LENGTH}")

    # Suspicious patterns
    # Detect corrupted future import/docstring compression on one physical line.
    # Use [ ] (space only, not \s) so newlines don't falsely match.
    docstring_markers = ('"""', "'''")
    future_import_marker = "from __future__" + " import"
    docstring_future_same_line = any(
        any(marker in line for marker in docstring_markers)
        and future_import_marker in line
        for line in lines
    ) or bool(
        re.search(r"from[ ]+__future__[ ]+import[ ]+annotations[ ]+from[ ]+\S", content)
    )
    if docstring_future_same_line:
        issues.append("contains docstring/future import compression")

    multiple_defs = False
    for line in lines:
        def_or_class_count = len(re.findall(r"(?<!\w)(?:class|def)\s+\w+", line))
        import_count = len(re.findall(r"(?<!\w)(?:from|import)\s+\S+", line))
        if def_or_class_count >= 2:
            multiple_defs = True
            issues.append("line has multiple class/def statements")
            break
        if import_count >= 4:
            multiple_defs = True
            issues.append("line has many import statements")
            break

    # R0: Detect suspicious literal \\n sequences where real newlines expected.
    # Heuristic: if a short file (<20 lines) has many literal \\n occurrences
    # outside of obvious string contexts, it may be line-compressed.
    literal_backslash_n_count = content.count("\\n")
    if line_count < 20 and literal_backslash_n_count > 30:
        suspicious = True
        issues.append(
            f"suspicious literal \\n count ({literal_backslash_n_count}) "
            f"in short file ({line_count} lines)"
        )

    # R0: Detect from __future__ import annotations after non-docstring code.
    future_import_after_code = False
    future_import_marker = "from __future__" + " import annotations"
    seen_future = False
    seen_code = False
    in_module_docstring = False
    module_docstring_seen = False
    module_docstring_quote = ""
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if in_module_docstring:
            if module_docstring_quote and module_docstring_quote in stripped:
                in_module_docstring = False
            continue
        if future_import_marker in stripped:
            seen_future = True
            if seen_code:
                future_import_after_code = True
                issues.append("from __future__ import annotations appears after code")
                break
            continue
        if not seen_future and not seen_code and not module_docstring_seen:
            for quote in ('"""', "'''"):
                if stripped.startswith(quote):
                    module_docstring_seen = True
                    if stripped.count(quote) == 1:
                        in_module_docstring = True
                        module_docstring_quote = quote
                    break
            if module_docstring_seen:
                continue
        if not seen_future:
            seen_code = True

    # Heuristic suspicious
    if line_count <= 5 and size > 1000:
        suspicious = True
        issues.append(f"only {line_count} lines but {size} bytes")
    if not _is_exempt_from_local_path_check(rel) and LOCAL_ABSOLUTE_PATH_RE.search(content):
        suspicious = True
        issues.append("contains local absolute /Users path")
    if ast_ok is False:
        suspicious = True

    if ("padding" + " line ") in content:
        suspicious = True
        issues.append("contains artificial padding lines")

    # Critical file minimum line counts
    if rel in MIN_LINE_COUNTS and line_count < MIN_LINE_COUNTS[rel]:
        issues.append(
            f"critical file needs >= {MIN_LINE_COUNTS[rel]} lines, has {line_count}"
        )
        suspicious = True

    literal_nl_suspicious = line_count < 20 and literal_backslash_n_count > 30

    return FileAudit(
        path=rel,
        line_count=line_count,
        max_line_length=max_line_len,
        file_size_bytes=size,
        suspicious_single_line=suspicious,
        python_ast_ok=ast_ok,
        yaml_parse_ok=None,
        contains_docstring_future_same_line=docstring_future_same_line,
        contains_multiple_top_level_defs_one_line=multiple_defs,
        issue_summary="; ".join(issues) if issues else "ok",
        future_import_after_code=future_import_after_code,
        suspicious_literal_newlines=literal_nl_suspicious,
        contains_hidden_line_separator=has_hidden_line_separator,
        contains_bidi_control=has_bidi_control,
    )


def _check_yaml(path: Path, root: Path) -> FileAudit:
    """Run YAML-specific integrity checks."""
    rel = str(path.relative_to(root))
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = _physical_lf_lines(content)
    size = path.stat().st_size
    line_count = len(lines)
    issues: list[str] = []
    hidden_issues, has_hidden_line_separator, has_bidi_control = _hidden_unicode_issues(content)

    yaml_ok: bool | None = None
    if yaml is not None:
        try:
            data = yaml.safe_load(content)
            yaml_ok = True
            # CI workflows must have the top-level keys GitHub Actions needs.
            if ".github/workflows/" in rel:
                required = {"name", "jobs"}
                keys = set(data.keys()) if isinstance(data, dict) else set()
                missing = sorted(required - keys)
                if isinstance(data, dict) and "on" not in data and True not in data:
                    missing.append("on")
                elif not isinstance(data, dict):
                    missing.append("on")
                if missing:
                    issues.append(f"CI workflow missing top-level keys: {', '.join(missing)}")
        except yaml.YAMLError as exc:
            yaml_ok = False
            issues.append(f"yaml.safe_load failed: {exc}")
    else:
        issues.append("PyYAML not available")

    suspicious = False
    if hidden_issues:
        suspicious = True
        issues.extend(hidden_issues)
    if line_count <= 5 and size > 1000:
        suspicious = True
        issues.append(f"only {line_count} lines but {size} bytes")
    if yaml_ok is False:
        suspicious = True

    max_line_len = max((len(line) for line in lines), default=0)
    if max_line_len > MAX_SOURCE_LINE_LENGTH:
        suspicious = True
        issues.append(f"max line length {max_line_len} > {MAX_SOURCE_LINE_LENGTH}")

    if not _is_exempt_from_local_path_check(rel) and LOCAL_ABSOLUTE_PATH_RE.search(content):
        suspicious = True
        issues.append("contains local absolute /Users path")

    # Critical file minimum line counts
    if rel in MIN_LINE_COUNTS and line_count < MIN_LINE_COUNTS[rel]:
        issues.append(
            f"critical file needs >= {MIN_LINE_COUNTS[rel]} lines, has {line_count}"
        )
        suspicious = True

    return FileAudit(
        path=rel,
        line_count=line_count,
        max_line_length=max_line_len,
        file_size_bytes=size,
        suspicious_single_line=suspicious,
        python_ast_ok=None,
        yaml_parse_ok=yaml_ok,
        contains_docstring_future_same_line=False,
        contains_multiple_top_level_defs_one_line=False,
        issue_summary="; ".join(issues) if issues else "ok",
        contains_hidden_line_separator=has_hidden_line_separator,
        contains_bidi_control=has_bidi_control,
    )


def _check_generic(path: Path, root: Path) -> FileAudit:
    """Fallback check for non-Python/YAML files."""
    rel = str(path.relative_to(root))
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = _physical_lf_lines(content)
    size = path.stat().st_size
    line_count = len(lines)
    max_line_len = max((len(line) for line in lines), default=0)
    issues: list[str] = []
    suspicious = False
    hidden_issues, has_hidden_line_separator, has_bidi_control = _hidden_unicode_issues(content)
    if hidden_issues:
        suspicious = True
        issues.extend(hidden_issues)

    if max_line_len > MAX_SOURCE_LINE_LENGTH:
        suspicious = True
        issues.append(f"max line length {max_line_len} > {MAX_SOURCE_LINE_LENGTH}")
    if not _is_exempt_from_local_path_check(rel) and LOCAL_ABSOLUTE_PATH_RE.search(content):
        suspicious = True
        issues.append("contains local absolute /Users path")
    if line_count <= 5 and size > 1000:
        suspicious = True
        issues.append(f"only {line_count} lines but {size} bytes")

    return FileAudit(
        path=rel,
        line_count=line_count,
        max_line_length=max_line_len,
        file_size_bytes=size,
        suspicious_single_line=suspicious,
        python_ast_ok=None,
        yaml_parse_ok=None,
        contains_docstring_future_same_line=False,
        contains_multiple_top_level_defs_one_line=False,
        issue_summary="; ".join(issues) if issues else "ok (non-Python/YAML file)",
        contains_hidden_line_separator=has_hidden_line_separator,
        contains_bidi_control=has_bidi_control,
    )


def _check_shell(path: Path, root: Path) -> FileAudit:
    """Run shell-script-specific integrity checks including bash -n syntax."""
    rel = str(path.relative_to(root))
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = _physical_lf_lines(content)
    size = path.stat().st_size
    line_count = len(lines)
    max_line_len = max((len(line) for line in lines), default=0)
    issues: list[str] = []
    suspicious = False
    hidden_issues, has_hidden_line_separator, has_bidi_control = _hidden_unicode_issues(content)
    if hidden_issues:
        suspicious = True
        issues.extend(hidden_issues)

    if max_line_len > MAX_SOURCE_LINE_LENGTH:
        suspicious = True
        issues.append(f"max line length {max_line_len} > {MAX_SOURCE_LINE_LENGTH}")

    if not _is_exempt_from_local_path_check(rel) and LOCAL_ABSOLUTE_PATH_RE.search(content):
        suspicious = True
        issues.append("contains local absolute /Users path")

    if line_count <= 5 and size > 1000:
        suspicious = True
        issues.append(f"only {line_count} lines but {size} bytes")

    # bash -n syntax check
    bash_ok: bool | None = None
    try:
        result = subprocess.run(
            ["bash", "-n", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        bash_ok = result.returncode == 0
        if not bash_ok:
            suspicious = True
            issues.append(f"bash -n failed: {result.stderr.strip()[:200]}")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        bash_ok = None
        issues.append(f"bash -n check skipped: {exc}")

    # Critical file minimum line counts
    if rel in MIN_LINE_COUNTS and line_count < MIN_LINE_COUNTS[rel]:
        issues.append(
            f"critical file needs >= {MIN_LINE_COUNTS[rel]} lines, has {line_count}"
        )
        suspicious = True

    return FileAudit(
        path=rel,
        line_count=line_count,
        max_line_length=max_line_len,
        file_size_bytes=size,
        suspicious_single_line=suspicious,
        python_ast_ok=None,
        yaml_parse_ok=None,
        contains_docstring_future_same_line=False,
        contains_multiple_top_level_defs_one_line=False,
        issue_summary="; ".join(issues) if issues else "ok",
        contains_hidden_line_separator=has_hidden_line_separator,
        contains_bidi_control=has_bidi_control,
    )


def run_audit(root: Path | None = None) -> list[FileAudit]:
    """Run the full audit and return a list of FileAudit records."""
    base = root or ROOT
    results: list[FileAudit] = []

    for path in _resolve_scan_paths(base):
        rel = str(path.relative_to(base))
        suffix = path.suffix
        if suffix == ".py":
            results.append(_check_python(path, base))
        elif suffix in (".yml", ".yaml"):
            results.append(_check_yaml(path, base))
        elif suffix == ".sh":
            results.append(_check_shell(path, base))
        else:
            results.append(_check_generic(path, base))

    return results


def write_json(audits: list[FileAudit], output_dir: Path) -> dict[str, Any]:
    """Write JSON report and return summary dict."""
    summary: dict[str, Any] = {
        "total_files": len(audits),
        "suspicious_count": sum(1 for a in audits if a.suspicious_single_line),
        "python_suspicious": sum(
            1 for a in audits if a.suspicious_single_line and a.python_ast_ok is not None
        ),
        "yaml_suspicious": sum(
            1 for a in audits if a.suspicious_single_line and a.yaml_parse_ok is not None
        ),
        "audits": [asdict(a) for a in audits],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "text_integrity_audit.json"
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def write_markdown(audits: list[FileAudit], output_dir: Path, summary: dict[str, Any]) -> None:
    """Write a human-readable Markdown report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Text Integrity Audit Report",
        "",
        "## Summary",
        "",
        f"- Total files scanned: {summary['total_files']}",
        f"- Suspicious files: {summary['suspicious_count']}",
        f"- Suspicious Python files: {summary['python_suspicious']}",
        f"- Suspicious YAML files: {summary['yaml_suspicious']}",
        "",
    ]

    suspicious_items = [a for a in audits if a.suspicious_single_line]
    if suspicious_items:
        lines.append("## Suspicious Files")
        lines.append("")
        lines.append(
            "| Path | Lines | Max Line | Size | AST/YAML | Issues |"
        )
        lines.append(
            "|------|-------|----------|------|----------|--------|"
        )
        for item in suspicious_items:
            ast_yaml = ""
            if item.python_ast_ok is not None:
                ast_yaml = "PASS" if item.python_ast_ok else "FAIL"
            if item.yaml_parse_ok is not None:
                ast_yaml = "PASS" if item.yaml_parse_ok else "FAIL"
            lines.append(
                f"| {item.path} | {item.line_count} | {item.max_line_length} "
                f"| {item.file_size_bytes} | {ast_yaml} | {item.issue_summary} |"
            )
        lines.append("")
    else:
        lines.append("## No suspicious files detected.")
        lines.append("")

    # Top 30 by max line length
    top30 = sorted(audits, key=lambda a: a.max_line_length, reverse=True)[:30]
    lines.append("## Top 30 Files by Max Line Length")
    lines.append("")
    lines.append("| Path | Lines | Max Line | Size | Status |")
    lines.append("|------|-------|----------|------|--------|")
    for item in top30:
        status = "SUSPICIOUS" if item.suspicious_single_line else "OK"
        lines.append(
            f"| {item.path} | {item.line_count} | {item.max_line_length} "
            f"| {item.file_size_bytes} | {status} |"
        )
    lines.append("")

    md_path = output_dir / "text_integrity_audit.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Markdown report written to {md_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentLab Text Integrity Audit")
    parser.add_argument(
        "--fail-on-suspicious",
        action="store_true",
        help="Exit with code 1 if any suspicious files found",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for audit reports",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    audits = run_audit()

    summary = write_json(audits, output_dir)
    write_markdown(audits, output_dir, summary)

    # Console summary
    suspicious_count = summary["suspicious_count"]
    print(f"\nTotal files scanned: {summary['total_files']}")
    print(f"Suspicious files: {suspicious_count}")

    if suspicious_count > 0:
        print("\nSuspicious files:")
        for a in audits:
            if a.suspicious_single_line:
                print(f"  - {a.path}: {a.issue_summary}")

    if args.fail_on_suspicious and suspicious_count > 0:
        print("\nFAIL: Suspicious files detected.")
        raise SystemExit(1)

    print("\nPASS: No suspicious files or --fail-on-suspicious not set.")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
