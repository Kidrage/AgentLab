"""Lightweight External Skill Workflow CLI.

This module closes the P1-A workflow without executing ECC, hooks, commands,
MCP servers, AnySearch, CodeGraph, or external IDE handoff.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import argparse
import json
import sys

import yaml

RUNTIME_DIR = Path(__file__).resolve().parent
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from atomic_io import safe_read_json, safe_read_yaml
from external_agents.ecc_inventory import load_ecc_config, scan_ecc_inventory
from skills.config_validation import (
    validate_ecc_integration_config,
    validate_external_skill_registry,
    validate_skill_incubation_policy,
)
from skills.incubation import load_incubation_policy, propose_internal_skill_candidates, write_incubation_artifacts
from skills.registry import import_inventory_records, load_skill_registry, write_skill_registry
from skills.usage_ledger import load_skill_usage_ledger


def default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def artifact_dir(agentlab_root: Path, project: str | None = None, task_id: str | None = None) -> Path:
    if project and task_id:
        return agentlab_root / "projects" / project / "runs" / task_id / "artifacts"
    return agentlab_root / "artifacts"


def inventory_path(agentlab_root: Path) -> Path:
    return artifact_dir(agentlab_root) / "external_skill_inventory.json"


def _print(data: Any, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    elif isinstance(data, str):
        print(data)
    else:
        print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True).rstrip())


def cmd_list(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    registry = load_skill_registry(root)
    messages = validate_external_skill_registry(registry)
    rows = []
    for skill in registry.get("external_skills", []) or []:
        license_info = skill.get("license") or {}
        rows.append({
            "skill_id": skill.get("skill_id"),
            "source": skill.get("source"),
            "enabled": skill.get("enabled", False),
            "capabilities": skill.get("capabilities") or [],
            "risk_level": (skill.get("risk") or {}).get("level"),
            "license_review_status": "required" if license_info.get("license_review_required") else "not_required",
        })
    _print({"skills": rows, "count": len(rows), "validation": messages}, as_json=args.json)
    return 0


def cmd_scan_ecc(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    config = load_ecc_config(root)
    messages = validate_ecc_integration_config(config)
    out = inventory_path(root)
    inventory = scan_ecc_inventory(root, config=config, output_path=out)
    inventory.setdefault("warnings", []).extend(messages)
    # Re-write only the JSON artifact after appending validation warnings.
    from atomic_io import atomic_write_json

    atomic_write_json(out, inventory)
    _print({"inventory_path": str(out), "found": inventory.get("found"), "warnings": inventory.get("warnings", [])}, as_json=args.json)
    return 0


def _load_inventory(root: Path) -> dict[str, Any]:
    return safe_read_json(inventory_path(root), default={}) or {}


def cmd_import_ecc(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    inventory = _load_inventory(root)
    records = list(inventory.get("agents", []) or []) + list(inventory.get("skills", []) or [])
    preview = [{"skill_id": record.get("id"), "name": record.get("name"), "type": record.get("type")} for record in records]
    if args.dry_run:
        _print({"dry_run": True, "would_import": preview, "registry_modified": False}, as_json=args.json)
        return 0
    registry = load_skill_registry(root)
    ecc_config = load_ecc_config(root)
    max_imported = int(((ecc_config.get("ecc") or {}).get("import_policy") or {}).get("max_imported_skills", 80))
    imported = import_inventory_records(registry, inventory, overwrite=True, max_imported=max_imported)
    write_skill_registry(root, registry)
    _print({"dry_run": False, "imported": imported, "registry_modified": True}, as_json=args.json)
    return 0


def _usage_path(root: Path, project: str, task_id: str) -> Path:
    run_dir = root / "projects" / project / "runs" / task_id
    for name in ("skill_usage_ledger.yml", "skill_usage.yml"):
        path = run_dir / name
        if path.exists():
            return path
    return run_dir / "skill_usage_ledger.yml"


def cmd_incubate(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    project = args.project
    task_id = args.task_id
    registry = load_skill_registry(root)
    policy = load_incubation_policy(root)
    warnings = validate_external_skill_registry(registry) + validate_skill_incubation_policy(policy)
    usage_file = _usage_path(root, project, task_id)
    if not usage_file.exists():
        usage = {"schema_version": 1, "task_id": task_id, "entries": []}
        warnings.append(f"warning: usage ledger not found: {usage_file}")
    else:
        usage = load_skill_usage_ledger(usage_file)
    candidates = propose_internal_skill_candidates(registry, usage, policy, task_context={"task_id": task_id, "project": project})
    paths = write_incubation_artifacts(artifact_dir(root, project, task_id), task_id=task_id, candidates=candidates, warnings=warnings)
    _print({"candidates": len(candidates), "paths": {k: str(v) for k, v in paths.items()}, "warnings": warnings}, as_json=args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AgentLab external skill workflow CLI")
    parser.add_argument("--root", default=str(default_root()), help="AgentLab repository root")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of YAML")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List external skills without executing external tools").set_defaults(func=cmd_list)
    sub.add_parser("scan-ecc", help="Run static ECC inventory scan only").set_defaults(func=cmd_scan_ecc)
    p_import = sub.add_parser("import-ecc", help="Import ECC inventory metadata into registry")
    p_import.add_argument("--dry-run", action="store_true", help="Preview imports without modifying registry")
    p_import.set_defaults(func=cmd_import_ecc)
    p_incubate = sub.add_parser("incubate", help="Write internal skill candidate artifacts for a task")
    p_incubate.add_argument("--task-id", required=True)
    p_incubate.add_argument("--project", default="AgentLab")
    p_incubate.set_defaults(func=cmd_incubate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())