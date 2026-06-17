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

# Minimum line counts for critical files
MIN_LINE_COUNTS = {
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


# Directories to always exclude from scanning
EXCLUDED_DIR_PARTS = {".venv", ".git", ".pytest_cache", "site-packages", "__pycache__", "node_modules", "dist", "build", "htmlcov", ".mypy_cache", ".ruff_cache"}
LOCAL_ABSOLUTE_PATH_RE = re.compile("/" + "Users" + r"/[^\s`'\"<>]+")
MAX_SOURCE_LINE_LENGTH = 1000


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
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    size = path.stat().st_size
    line_count = len(lines)
    issues: list[str] = []
    suspicious = False

    # AST parse
    ast_ok: bool | None = None
    try:
        ast.parse(path.read_text(encoding="utf-8", errors="replace"))
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
    content = path.read_text(encoding="utf-8", errors="replace")
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
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if future_import_marker in stripped:
            seen_future = True
            if seen_code:
                future_import_after_code = True
                issues.append("from __future__ import annotations appears after code")
                break
            continue
        if stripped.startswith(('"""', "'''")):
            continue
        if not seen_future:
            seen_code = True

    # Heuristic suspicious
    if line_count <= 5 and size > 1000:
        suspicious = True
        issues.append(f"only {line_count} lines but {size} bytes")
    if LOCAL_ABSOLUTE_PATH_RE.search(content):
        suspicious = True
        issues.append("contains local absolute /Users path")
    if ast_ok is False:
        suspicious = True

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
    )


def _check_yaml(path: Path, root: Path) -> FileAudit:
    """Run YAML-specific integrity checks."""
    rel = str(path.relative_to(root))
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    size = path.stat().st_size
    line_count = len(lines)
    issues: list[str] = []

    yaml_ok: bool | None = None
    if yaml is not None:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
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
    if line_count <= 5 and size > 1000:
        suspicious = True
        issues.append(f"only {line_count} lines but {size} bytes")
    if yaml_ok is False:
        suspicious = True

    max_line_len = max((len(line) for line in lines), default=0)
    if max_line_len > MAX_SOURCE_LINE_LENGTH:
        suspicious = True
        issues.append(f"max line length {max_line_len} > {MAX_SOURCE_LINE_LENGTH}")

    content = path.read_text(encoding="utf-8", errors="replace")
    if LOCAL_ABSOLUTE_PATH_RE.search(content):
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
    )


def _check_generic(path: Path, root: Path) -> FileAudit:
    """Fallback check for non-Python/YAML files."""
    rel = str(path.relative_to(root))
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    size = path.stat().st_size
    line_count = len(lines)
    max_line_len = max((len(line) for line in lines), default=0)
    issues: list[str] = []
    suspicious = False

    if max_line_len > MAX_SOURCE_LINE_LENGTH:
        suspicious = True
        issues.append(f"max line length {max_line_len} > {MAX_SOURCE_LINE_LENGTH}")
    content = path.read_text(encoding="utf-8", errors="replace")
    if LOCAL_ABSOLUTE_PATH_RE.search(content):
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
    )


def _check_shell(path: Path, root: Path) -> FileAudit:
    """Run shell-script-specific integrity checks including bash -n syntax."""
    rel = str(path.relative_to(root))
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    size = path.stat().st_size
    line_count = len(lines)
    max_line_len = max((len(line) for line in lines), default=0)
    issues: list[str] = []
    suspicious = False

    if max_line_len > MAX_SOURCE_LINE_LENGTH:
        suspicious = True
        issues.append(f"max line length {max_line_len} > {MAX_SOURCE_LINE_LENGTH}")

    content = path.read_text(encoding="utf-8", errors="replace")
    if LOCAL_ABSOLUTE_PATH_RE.search(content):
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
