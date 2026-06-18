"""S4 mock sandbox validation for skill packages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_SANDBOX_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "skill_sandbox_policy.yml"

DEFAULT_SANDBOX_POLICY: dict[str, Any] = {
    "schema_version": 1,
    "mode": "mock",
    "execute_code": False,
    "required_files": ["SKILL.md"],
}


def load_sandbox_policy(path: Path | str | None = None) -> dict[str, Any]:
    policy_path = Path(path) if path is not None else DEFAULT_SANDBOX_POLICY_PATH
    policy = dict(DEFAULT_SANDBOX_POLICY)
    if policy_path.exists():
        data = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            policy.update(data)
    policy["execute_code"] = False
    policy["mode"] = "mock"
    return policy


def run_mock_sandbox(
    package_path: Path | str,
    parsed_skill: dict[str, Any],
    trust_report: dict[str, Any],
    permission_report: dict[str, Any],
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate package metadata without executing code."""

    policy = policy or load_sandbox_policy()
    path = Path(package_path)
    root = path if path.is_dir() else path.parent
    checked_files: list[dict[str, Any]] = []
    errors: list[str] = []
    for name in policy.get("required_files") or ["SKILL.md"]:
        file_path = root / str(name)
        exists = file_path.exists() and file_path.is_file()
        checked_files.append({"file": str(name), "exists": exists})
        if not exists:
            errors.append(f"required file missing: {name}")

    if parsed_skill.get("validation_errors"):
        errors.extend(str(item) for item in parsed_skill["validation_errors"])
    if not trust_report.get("passed", False):
        errors.append("trust scan did not pass")
    if not permission_report.get("passed", False):
        errors.append("permission manifest did not pass")

    return {
        "schema_version": 1,
        "skill_id": parsed_skill.get("skill_id"),
        "mode": "mock",
        "executed_code": False,
        "checked_files": checked_files,
        "errors": list(dict.fromkeys(errors)),
        "passed": not errors,
        "notes": ["Mock sandbox only; no external code, shell, or network was executed."],
    }
