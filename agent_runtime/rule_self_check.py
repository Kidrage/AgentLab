"""Deterministic rule-based self-check engine for AgentLab.

Performs: git check, changed file scan, secret scan, YAML/Python/Shell
syntax validation, report completeness, state consistency.
Never calls an LLM for pass/fail decisions.
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from atomic_io import safe_read_yaml
from git_utils import parse_porcelain_z


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    try:
        result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=30)
        return result.returncode, result.stdout, result.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 1, "", str(e)


def run_self_check(
    agentlab_root: Path,
    project: str,
    task_id: str,
    *,
    strict: bool = False,
) -> dict:
    """Run all rule-based checks and return a self_check_report dict.

    Parameters:
        agentlab_root: resolved absolute path to the AgentLab repo root
        project: project name
        task_id: task id
        strict: treat warnings as failures
    """
    checks: list[dict] = []
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Load policy
    policy_path = agentlab_root / "config" / "self_check_policy.yml"
    policy = safe_read_yaml(policy_path) or {}

    # ── 1. Git repository check ─────────────────────────────────────────
    rc, stdout, stderr = _run(["git", "rev-parse", "--is-inside-work-tree"], agentlab_root)
    checks.append({
        "id": "git_worktree",
        "status": "pass" if rc == 0 else "fail",
        "severity": "critical" if rc != 0 else "info",
        "message": "Git worktree detected." if rc == 0 else f"Not a git repository: {stderr.strip()}",
    })

    # ── 2. Changed file scan ───────────────────────────────────────────
    rc, stdout, _ = _run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], agentlab_root)
    changed_files: list[str] = []
    if rc == 0:
        changed_files = parse_porcelain_z(stdout)

    # Blocked patterns check
    blocked = policy.get("path_policy", {}).get("blocked_patterns", [])
    blocked_files: list[str] = []
    for f in changed_files:
        for pat in blocked:
            # Simple glob match
            if _match_pattern(f, pat):
                blocked_files.append(f)
                break

    checks.append({
        "id": "changed_files",
        "status": "fail" if blocked_files else "pass",
        "severity": "critical" if blocked_files else "info",
        "message": f"{len(changed_files)} changed files"
                    + (f", {len(blocked_files)} blocked" if blocked_files else ""),
        "details": {"changed": changed_files, "blocked": blocked_files},
    })

    # ── 3. Secret scan ─────────────────────────────────────────────────
    secret_scan = policy.get("secret_scan", {})
    secret_fail = False
    if secret_scan.get("enabled", True):
        patterns = secret_scan.get("patterns", [])
        max_mb = secret_scan.get("max_file_mb", 5)
        for f in changed_files:
            fp = agentlab_root / f
            if not fp.exists() or not fp.is_file():
                continue
            if fp.stat().st_size > max_mb * 1024 * 1024:
                continue
            try:
                content = fp.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pat_str in patterns:
                pat = re.compile(pat_str, re.IGNORECASE)
                if pat.search(content):
                    secret_fail = True
                    checks.append({
                        "id": "secret_scan",
                        "status": "fail",
                        "severity": "critical",
                        "message": f"Possible secret detected in {f} (pattern matched, not printed).",
                    })
                    break
            if secret_fail:
                break
    if not secret_fail:
        checks.append({
            "id": "secret_scan",
            "status": "pass",
            "severity": "critical",
            "message": "No obvious secrets detected.",
        })

    # ── 4. YAML validation ────────────────────────────────────────────
    yaml_fail = False
    for f in changed_files:
        if f.endswith((".yml", ".yaml")):
            fp = agentlab_root / f
            if fp.exists():
                try:
                    yaml.safe_load(fp.read_text(encoding="utf-8"))
                except yaml.YAMLError as e:
                    yaml_fail = True
                    checks.append({
                        "id": "yaml_syntax",
                        "status": "fail",
                        "severity": "critical",
                        "message": f"Invalid YAML in {f}: {e}",
                    })
    if not yaml_fail:
        checks.append({
            "id": "yaml_syntax",
            "status": "pass",
            "severity": "critical",
            "message": "All changed YAML files parse correctly.",
        })

    # ── 5. Python syntax validation ────────────────────────────────────
    py_fail = False
    for f in changed_files:
        if f.endswith(".py"):
            fp = agentlab_root / f
            if fp.exists():
                rc, _, stderr = _run([sys.executable, "-m", "py_compile", str(fp)], agentlab_root)
                if rc != 0:
                    py_fail = True
                    checks.append({
                        "id": "python_syntax",
                        "status": "fail",
                        "severity": "critical",
                        "message": f"Python syntax error in {f}: {stderr.strip()[:200]}",
                    })
    if not py_fail:
        checks.append({
            "id": "python_syntax",
            "status": "pass",
            "severity": "critical",
            "message": "All changed Python files compile.",
        })

    # ── 6. Shell syntax validation ─────────────────────────────────────
    sh_fail = False
    for f in changed_files:
        if f.endswith(".sh"):
            fp = agentlab_root / f
            if fp.exists():
                rc, _, stderr = _run(["bash", "-n", str(fp)], agentlab_root)
                if rc != 0:
                    sh_fail = True
                    checks.append({
                        "id": "shell_syntax",
                        "status": "fail",
                        "severity": "critical",
                        "message": f"Shell syntax error in {f}: {stderr.strip()[:200]}",
                    })
    if not sh_fail:
        checks.append({
            "id": "shell_syntax",
            "status": "pass",
            "severity": "critical",
            "message": "All changed shell scripts pass bash -n.",
        })

    # ── 7. Git diff whitespace ─────────────────────────────────────────
    rc, _, stderr = _run(["git", "diff", "--check"], agentlab_root)
    checks.append({
        "id": "git_diff_whitespace",
        "status": "warn" if rc != 0 else "pass",
        "severity": "warning",
        "message": "No whitespace issues." if rc == 0 else f"Whitespace issues: {stderr.strip()[:200]}",
    })

    # ── 8. Report completeness ─────────────────────────────────────────
    report_policy = policy.get("report_completeness", {})
    if report_policy.get("enabled", True):
        has_code_changes = any(f.endswith((".py", ".sh", ".yml", ".yaml")) for f in changed_files)
        if has_code_changes:
            impl_path = run_dir / "implementation_report.md"
            has_report = impl_path.exists() and "TBD" not in impl_path.read_text(encoding="utf-8")[:200]
            checks.append({
                "id": "report_completeness",
                "status": "pass" if has_report else "warn",
                "severity": "warning",
                "message": "Implementation report found." if has_report else "No implementation report for code changes.",
            })
        else:
            checks.append({
                "id": "report_completeness",
                "status": "pass",
                "severity": "info",
                "message": "No code changes detected — skipping report check.",
            })

    # ── Summary ────────────────────────────────────────────────────────
    passed = sum(1 for c in checks if c["status"] == "pass")
    warnings = sum(1 for c in checks if c["status"] == "warn")
    failed = sum(1 for c in checks if c["status"] == "fail")

    strict_warning_blockers = strict and warnings > 0
    overall = "fail" if failed > 0 else ("warn" if warnings > 0 else "pass")
    if strict and overall == "warn":
        overall = "fail"

    report = {
        "version": 1,
        "project": project,
        "task_id": task_id,
        "status": overall,
        "created_at": utc_now(),
        "summary": {
            "total_checks": len(checks),
            "passed": passed,
            "warnings": warnings,
            "failed": failed,
        },
        "checks": checks,
        "artifacts": {
            "changed_files": changed_files,
            "reports_written": ["self_check_report.yml"],
        },
        "blocking_reasons": [
            c["message"]
            for c in checks
            if c["status"] == "fail" or (strict_warning_blockers and c["status"] == "warn")
        ],
        "auto_sync_eligible": overall in ("pass", "warn") and not failed,
    }

    # Write report
    from atomic_io import atomic_write_yaml
    report_path = run_dir / "self_check_report.yml"
    atomic_write_yaml(report_path, report)

    return report


def _match_pattern(filename: str, pattern: str) -> bool:
    """Simple pattern matcher supporting * and **."""
    # Convert glob pattern to regex
    regex = re.escape(pattern)
    regex = regex.replace(r"\*\*", ".+").replace(r"\*", "[^/]*")
    # Match at any depth
    regex = f"(^|.*/){regex}$"
    return bool(re.match(regex, filename))
