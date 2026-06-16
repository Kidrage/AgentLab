from __future__ import annotations

import ast
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]

PYTHON_SCAN_ROOTS = [
    ROOT / "agent_runtime",
    ROOT / "tests",
]

YAML_SCAN_ROOTS = [
    ROOT / "config",
    ROOT / ".github" / "workflows",
]

ACCEPTANCE_SCAN_ROOT = ROOT / "acceptance_runs"

KNOWN_TINY_PYTHON_FILES = {
    "state_store.py",
    "atomic_io.py",
    "agent_runtime/ingestion/__init__.py",
    "agent_runtime/ingestion/repo_indexers/__init__.py",
    "agent_runtime/search/__init__.py",
    "agent_runtime/skills/__init__.py",
    "agent_runtime/external_agents/__init__.py",
    "agent_runtime/costing/__init__.py",
    "agent_runtime/recovery/__init__.py",
}

MIN_LINE_COUNTS = {
    ".github/workflows/ci.yml": 20,
    "agent_runtime/mcp_server.py": 100,
    "agent_runtime/skills/registry.py": 80,
    "agent_runtime/external_agents/ecc_inventory.py": 80,
    "agent_runtime/external_agents/handoff.py": 80,
    "agent_runtime/search/anysearch_adapter.py": 80,
    "agent_runtime/search/local_url_reader.py": 40,
    "agent_runtime/ingestion/repo_indexers/codegraph_adapter.py": 80,
    "agent_runtime/repo_index_cli.py": 40,
    "agent_runtime/p2_closure/closure_runner.py": 80,
    "agent_runtime/run_task.py": 80,
    "agent_runtime/truenas_sync.py": 500,
    "agent_runtime/skill_evolution.py": 500,
    "agent_runtime/post_task_learning.py": 100,
    "agent_runtime/external_skill_importer.py": 120,
    "agent_runtime/pipeline_runner.py": 120,
    "agent_runtime/search_cli.py": 80,
    "agent_runtime/search/provider.py": 40,
    "agent_runtime/search/policy.py": 40,
    "agent_runtime/skill_distiller.py": 200,
    "agent_runtime/skill_vault.py": 200,
    "agent_runtime/skill_backup.py": 100,
    "scripts/audit_text_integrity.py": 120,
    "tests/test_anysearch_adapter.py": 40,
    "tests/test_p1_cd_syntax_yaml_integrity.py": 40,
    "tests/test_external_skill_registry.py": 40,
    "tests/test_repository_text_integrity.py": 80,
    "tests/test_skill_vault.py": 80,
    "tests/test_skill_backup.py": 80,
    "tests/test_truenas_sync.py": 80,
    "tests/test_p2_closure.py": 80,
    "agentlab.sh": 20,
    "config/search_providers.yml": 10,
    "config/external_skill_import_policy.yml": 10,
    "config/skill_distillation.yml": 20,
    "config/skill_discovery.yml": 10,
    "config/repo_indexing.yml": 10,
    "config/backup_policy.yml": 200,
    "config/backup_policy.local.example.yml": 15,
    "config/skill_vault.yml": 20,
    "docs/SKILL_VAULT.md": 40,
    "scripts/check_remote_raw_integrity.py": 80,
    "tests/test_text_integrity_audit.py": 60,
    # P2-H: Context Governance Runtime Hardening
    "agent_runtime/context_governance/redaction.py": 80,
    "agent_runtime/context_governance/runtime_wiring.py": 80,
    "config/context_governance.yml": 25,
    "tests/test_context_governance_runtime_wiring.py": 80,
    "tests/test_context_governance_artifacts.py": 80,
    "tests/test_context_governance_cli.py": 80,
    "tests/test_context_governance_budget_costledger.py": 80,
    "tests/test_context_governance_redaction.py": 80,
    "tests/test_context_governance_p2h_closure.py": 80,
    # P2-I: Execution Reliability & Failure Recovery
    "agent_runtime/recovery/__init__.py": 30,
    "agent_runtime/recovery/failure_event.py": 80,
    "agent_runtime/recovery/failure_classifier.py": 80,
    "agent_runtime/recovery/diagnosis.py": 80,
    "agent_runtime/recovery/recovery_plan.py": 80,
    "agent_runtime/recovery/retry_policy.py": 80,
    "agent_runtime/recovery/verdict.py": 80,
    "config/failure_recovery.yml": 30,
    "scripts/p2_i_recovery_smoke.py": 80,
    "tests/test_failure_event_capture.py": 80,
    "tests/test_failure_classifier.py": 80,
    "tests/test_recovery_plan_retry.py": 80,
    "tests/test_p2_i_recovery.py": 80,
    "tests/test_recovery_text_integrity.py": 80,
    "tests/test_recovery_costledger_integration.py": 80,
    ".github/workflows/ci.yml": 25,
}


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in PYTHON_SCAN_ROOTS:
        files.extend(
            path
            for path in root.rglob("*.py")
            if "__pycache__" not in path.parts and ".venv" not in path.parts
        )
    for path in [ROOT / "agentlab_app.py", ROOT / "state_store.py", ROOT / "atomic_io.py"]:
        if path.exists():
            files.append(path)
    return sorted(set(files))


def _yaml_files() -> list[Path]:
    files: list[Path] = []
    for root in YAML_SCAN_ROOTS:
        files.extend(path for path in root.rglob("*.yml"))
        files.extend(path for path in root.rglob("*.yaml"))
    return sorted(set(files))


def _acceptance_artifact_files() -> list[Path]:
    if not ACCEPTANCE_SCAN_ROOT.exists():
        return []
    suffixes = {".md", ".yml", ".yaml"}
    return sorted(
        path
        for path in ACCEPTANCE_SCAN_ROOT.rglob("*")
        if path.is_file()
        and path.suffix in suffixes
        and ".venv" not in path.parts
        and "__pycache__" not in path.parts
    )


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _max_line_length(path: Path) -> int:
    lines = path.read_text(encoding="utf-8").splitlines()
    return max((len(line) for line in lines), default=0)


def test_python_files_parse() -> None:
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))


def test_yaml_files_parse() -> None:
    for path in _yaml_files():
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data is None or isinstance(data, (dict, list)), _relative(path)


def test_workflow_has_required_keys() -> None:
    workflow_dir = ROOT / ".github" / "workflows"
    workflows = sorted(workflow_dir.glob("*.yml")) + sorted(workflow_dir.glob("*.yaml"))
    assert workflows, "No GitHub Actions workflows found"

    for path in workflows:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), _relative(path)
        # PyYAML parses YAML 1.1 "on" as boolean True; accept both.
        has_on = "on" in data or True in data
        for key in ("name", "jobs"):
            assert key in data, f"{_relative(path)} missing top-level {key!r}"
        assert has_on, f"{_relative(path)} missing top-level 'on' (or YAML 1.1 'True')"


def test_critical_files_have_minimum_line_counts() -> None:
    for relative_path, minimum in MIN_LINE_COUNTS.items():
        path = ROOT / relative_path
        assert path.exists(), f"{relative_path} missing"
        count = _line_count(path)
        assert count >= minimum, f"{relative_path} has only {count} lines"


def test_no_extreme_long_source_lines() -> None:
    for path in _python_files() + _acceptance_artifact_files():
        relative_path = _relative(path)
        assert _max_line_length(path) <= 1200, (
            f"{relative_path} has a line over 1200 characters"
        )


def test_acceptance_artifacts_have_no_local_absolute_paths() -> None:
    local_path_pattern = re.compile("/" + "Users" + r"/[^\s`'\"<>]+")
    for path in _acceptance_artifact_files():
        text = path.read_text(encoding="utf-8")
        match = local_path_pattern.search(text)
        assert match is None, f"{_relative(path)} contains local absolute path {match.group(0)}"


def test_no_docstring_future_import_on_same_line() -> None:
    future_import_marker = "from __future__" + " import annotations"
    for path in _python_files():
        relative_path = _relative(path)
        lines = path.read_text(encoding="utf-8").splitlines()

        for number, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            if stripped.startswith('"""') and future_import_marker in line:
                raise AssertionError(
                    f"{relative_path}:{number} has docstring and future import on one line"
                )


def test_no_many_defs_or_classes_on_single_line() -> None:
    for path in _python_files():
        relative_path = _relative(path)
        lines = path.read_text(encoding="utf-8").splitlines()

        if relative_path not in KNOWN_TINY_PYTHON_FILES and path.name != "__init__.py":
            assert len(lines) >= 10, f"{relative_path} has only {len(lines)} lines"

        for number, line in enumerate(lines, start=1):
            top_level_defs = len(re.findall(r"(?<!\w)(?:class|def)\s+\w+", line))
            assert top_level_defs <= 1, (
                f"{relative_path}:{number} has multiple class/def statements on one line"
            )


def test_audit_script_flags_suspicious_fixture(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    suspicious = scripts_dir / "compressed.py"
    repeated_imports = " ".join(f"import module_{idx}" for idx in range(90))
    suspicious.write_text(
        f"from __future__ import annotations {repeated_imports}\n",
        encoding="utf-8",
    )

    spec = importlib.util.spec_from_file_location(
        "audit_text_integrity",
        ROOT / "scripts" / "audit_text_integrity.py",
    )
    assert spec is not None and spec.loader is not None
    audit_module = importlib.util.module_from_spec(spec)
    sys.modules["audit_text_integrity"] = audit_module
    spec.loader.exec_module(audit_module)

    audits = audit_module.run_audit(tmp_path)
    suspicious_paths = {audit.path for audit in audits if audit.suspicious_single_line}

    assert "scripts/compressed.py" in suspicious_paths


def test_shell_entrypoint_has_enough_lines() -> None:
    """The main shell entrypoint must have a minimum number of lines."""
    path = ROOT / "agentlab.sh"
    assert path.exists(), "agentlab.sh missing"
    count = _line_count(path)
    assert count >= 20, f"agentlab.sh has only {count} lines (need >= 20)"


def test_shell_entrypoint_passes_bash_syntax_check() -> None:
    """The main shell entrypoint must pass bash -n syntax check."""
    path = ROOT / "agentlab.sh"
    assert path.exists(), "agentlab.sh missing"
    result = subprocess.run(
        ["bash", "-n", str(path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"bash -n failed for agentlab.sh: {result.stderr.strip()}"


def test_shell_scripts_pass_bash_syntax_check() -> None:
    """All .sh files in scripts/ must pass bash -n syntax check."""
    scripts_dir = ROOT / "scripts"
    for sh_file in sorted(scripts_dir.glob("*.sh")):
        result = subprocess.run(
            ["bash", "-n", str(sh_file)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        rel = _relative(sh_file)
        assert result.returncode == 0, f"bash -n failed for {rel}: {result.stderr.strip()}"


def test_audit_script_is_not_compressed() -> None:
    """The audit script itself must not be compressed into too few lines."""
    path = ROOT / "scripts" / "audit_text_integrity.py"
    assert path.exists(), "audit_text_integrity.py missing"
    count = _line_count(path)
    assert count >= 120, f"audit_text_integrity.py has only {count} lines (need >= 120)"


def test_audit_script_itself_passes_bash_indirectly() -> None:
    """The audit script must be parseable as Python and self-auditable."""
    path = ROOT / "scripts" / "audit_text_integrity.py"
    assert path.exists(), "audit_text_integrity.py missing"
    source = path.read_text(encoding="utf-8")
    ast.parse(source, filename=str(path))


def test_yaml_policy_files_are_not_single_line_compressed() -> None:
    for relative_path in [
        "config/search_providers.yml",
        "config/external_skill_import_policy.yml",
        "config/skill_distillation.yml",
        "config/skill_discovery.yml",
        "config/skill_vault.yml",
        "config/backup_policy.yml",
    ]:
        path = ROOT / relative_path
        assert path.exists(), f"{relative_path} missing"
        assert _line_count(path) > 5, f"{relative_path} appears compressed"
        assert _max_line_length(path) <= 1000, f"{relative_path} has an extreme long line"


def test_agentlab_shell_is_readable_and_not_single_line_large_file() -> None:
    path = ROOT / "agentlab.sh"
    assert path.exists() and path.is_file()
    assert _line_count(path) >= 20
    assert _max_line_length(path) <= 1000


def test_skill_vault_is_gitignored() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "memory/global/skills/" in gitignore
    assert "!config/skill_vault.yml" in gitignore
    assert "!docs/SKILL_VAULT.md" in gitignore
