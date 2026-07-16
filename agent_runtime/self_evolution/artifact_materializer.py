"""Materialize the single declared output of a component-managed v1 role."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .role_catalog import RoleCatalog


def _write_contract(run_dir: Path, role_key: str, data: dict[str, Any]) -> Path:
    path = run_dir / f"component_role_output_contract_{role_key}.yml"
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def materialize_component_role_result(
    agentlab_root: Path,
    plan: Any,
    agent_name: str,
    result: Any,
    output_path: Path,
) -> tuple[bool, list[str], Path]:
    """Extract one exact AGENTLAB_EDIT artifact without persisting CLI wrappers."""

    catalog = RoleCatalog.load(agentlab_root)
    role = catalog.get(agent_name)
    run_dir = Path(plan.run_dir)
    if role is None or role.source != "component_manifest":
        contract = _write_contract(
            run_dir,
            "unknown",
            {"status": "blocked", "issues": ["role_is_not_component_managed"]},
        )
        return False, ["role_is_not_component_managed"], contract

    expected_output = run_dir / role.default_report
    issues: list[str] = []
    if output_path.is_symlink() or output_path.resolve(strict=False) != expected_output.resolve(
        strict=False
    ):
        issues.append("component_output_path_does_not_match_default_report")
    try:
        from agent_runtime.patch_applicator import parse_edit_blocks
    except ModuleNotFoundError:  # pragma: no cover - direct script path
        from patch_applicator import parse_edit_blocks

    blocks = parse_edit_blocks(str(getattr(result, "content", "") or ""))
    accepted: list[str] = []
    for block in blocks:
        raw_path = str(block.get("path") or "").strip().replace("\\", "/")
        parts = Path(raw_path).parts
        allowed_path = raw_path == role.default_report or (
            len(parts) == 3
            and parts[0] == "runs"
            and parts[1] == str(plan.task_id)
            and parts[2] == role.default_report
        )
        if not allowed_path:
            issues.append(f"unexpected_component_output:{raw_path or '<blank>'}")
            continue
        content = str(block.get("html_block_content") or "").strip()
        if not content:
            issues.append("component_output_is_empty")
            continue
        accepted.append(content)
    if len(accepted) != 1:
        issues.append("component_role_must_return_exactly_one_output_block")
    if accepted and expected_output.suffix.lower() in {".yml", ".yaml"}:
        try:
            parsed = yaml.safe_load(accepted[0])
        except yaml.YAMLError:
            parsed = None
        if not isinstance(parsed, dict):
            issues.append("component_yaml_output_must_be_a_mapping")

    if issues:
        expected_output.unlink(missing_ok=True)
        contract = _write_contract(
            run_dir,
            role.key,
            {
                "schema_version": 1,
                "status": "blocked",
                "role": role.display_name,
                "expected_output": role.default_report,
                "issues": sorted(set(issues)),
            },
        )
        return False, sorted(set(issues)), contract

    temporary = expected_output.with_name(f".{expected_output.name}.component.tmp")
    if temporary.is_symlink():
        raise ValueError("component output temporary path is a symlink")
    temporary.write_text(accepted[0], encoding="utf-8")
    temporary.replace(expected_output)
    contract = _write_contract(
        run_dir,
        role.key,
        {
            "schema_version": 1,
            "status": "pass",
            "role": role.display_name,
            "output": role.default_report,
            "cli_wrapper_persisted": False,
            "production_modified": False,
            "issues": [],
        },
    )
    return True, [], contract
