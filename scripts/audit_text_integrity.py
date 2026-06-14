#!/usr/bin/env python3
"""Audit repository text integrity for compressed Python/YAML/CI files.

The script is read-only for source/config files. It writes audit reports under
``acceptance_runs/stabilization`` so CI and reviewers can inspect suspected
text-compression regressions without mutating the codebase.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
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
    "tests/*.py",
    "config/*.yml",
    "config/*.yaml",
    "docs/*.md",
    "README.md",
    "agentlab.sh",
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
    "scripts/p2_provider_governance_check.py": 60,
    "scripts/audit_text_integrity.py": 120,
    "tests/test_repository_text_integrity.py": 80,
    "tests/test_p2_closure.py": 80,
    "agentlab.sh": 20,
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


# Directories to always exclude from scanning
EXCLUDED_DIR_PARTS = {".venv", "site-packages", "__pycache__", "node_modules"}


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

    # Suspicious patterns
    content = path.read_text(encoding="utf-8", errors="replace")
    # Detect corrupted future import/docstring compression on one physical line.
    # Use [ ] (space only, not \s) so newlines don't falsely match.
    docstring_future_same_line = any(
        ('"""' in line or "'''" in line) and "from __future__ import" in line
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

    # Shebang followed by code on same line
    if lines and lines[0].startswith("#!"):
        shebang_rest = lines[0][2:].strip()
        if "python" in shebang_rest.lower():
            parts = shebang_rest.split()
            if len(parts) > 1 and not parts[-1].startswith("#"):
                issues.append("shebang with code on same line")

    # Heuristic suspicious
    suspicious = False
    if line_count < 5 and size > 500:
        suspicious = True
        issues.append(f"only {line_count} lines but {size} bytes")
    if max_line_len > 2000:
        suspicious = True
        issues.append(f"max line length {max_line_len} > 2000")
    if ast_ok is False:
        suspicious = True

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
        python_ast_ok=ast_ok,
        yaml_parse_ok=None,
        contains_docstring_future_same_line=docstring_future_same_line,
        contains_multiple_top_level_defs_one_line=multiple_defs,
        issue_summary="; ".join(issues) if issues else "ok",
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
    if line_count < 3 and size > 200:
        suspicious = True
        issues.append(f"only {line_count} lines but {size} bytes")
    if yaml_ok is False:
        suspicious = True

    max_line_len = max((len(line) for line in lines), default=0)
    if max_line_len > 2000:
        suspicious = True
        issues.append(f"max line length {max_line_len} > 2000")

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

    return FileAudit(
        path=rel,
        line_count=line_count,
        max_line_length=max_line_len,
        file_size_bytes=size,
        suspicious_single_line=False,
        python_ast_ok=None,
        yaml_parse_ok=None,
        contains_docstring_future_same_line=False,
        contains_multiple_top_level_defs_one_line=False,
        issue_summary="ok (non-Python/YAML file)",
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
