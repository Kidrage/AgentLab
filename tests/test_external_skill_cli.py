from __future__ import annotations

import json
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from external_skills_cli import main


def _write_base_config(root: Path) -> None:
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "external_skill_registry.yml").write_text(yaml.safe_dump({
        "schema_version": 1,
        "external_skills": [{
            "skill_id": "ecc.planner",
            "source": "ecc",
            "source_type": "external_agent_pack",
            "display_name": "ECC Planner",
            "integration_mode": "inventory_only",
            "enabled": False,
            "capabilities": ["planning"],
            "risk": {"level": "medium", "requires_approval": True},
            "license": {"name": "unknown", "license_review_required": True},
        }],
    }, sort_keys=False), encoding="utf-8")
    (config / "ecc_integration.yml").write_text(yaml.safe_dump({
        "ecc": {
            "enabled": False,
            "mode": "inventory_only",
            "local_paths": [str(root / "missing-ecc")],
            "scan": {"allow_markdown_scan": True, "allow_json_yaml_scan": True, "max_files": 20, "max_file_kb": 64},
            "import_policy": {"default_enabled": False, "require_manual_enable": True, "max_imported_skills": 80, "allow_commands": False, "allow_hooks": False, "allow_mcp_servers": False},
            "risk_defaults": {"level": "medium", "requires_approval": True},
        }
    }, sort_keys=False), encoding="utf-8")
    (config / "skill_incubation_policy.yml").write_text(yaml.safe_dump({
        "skill_incubation": {
            "enabled": True,
            "budget": {"max_incubation_cost_usd_per_task": 0.03, "max_incubation_tokens_per_task": 12000, "max_candidates_per_task": 3},
            "triggers": {"min_successful_uses": 2, "min_quality_score": 0.75, "trigger_on_external_dependency_risk": True, "trigger_on_high_reuse_potential": True},
            "forbidden_outputs": ["copied_external_source_code", "secrets", "private_tokens"],
            "review_required": True,
        }
    }, sort_keys=False), encoding="utf-8")


def _run_cli(root: Path, *args: str) -> str:
    out = StringIO()
    with redirect_stdout(out):
        assert main(["--root", str(root), "--json", *args]) == 0
    return out.getvalue()


def test_external_skills_list_cli_reads_registry(tmp_path: Path) -> None:
    _write_base_config(tmp_path)
    output = _run_cli(tmp_path, "list")
    data = json.loads(output)
    assert data["skills"][0]["skill_id"] == "ecc.planner"
    assert data["skills"][0]["enabled"] is False


def test_import_ecc_dry_run_does_not_modify_registry(tmp_path: Path) -> None:
    _write_base_config(tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "external_skill_inventory.json").write_text(json.dumps({
        "source": "ecc",
        "agents": [{"id": "ecc.code-reviewer", "name": "code-reviewer", "type": "agent", "capabilities": ["code_review"]}],
        "skills": [],
    }), encoding="utf-8")
    registry_path = tmp_path / "config" / "external_skill_registry.yml"
    before = registry_path.read_text(encoding="utf-8")
    output = _run_cli(tmp_path, "import-ecc", "--dry-run")
    assert json.loads(output)["registry_modified"] is False
    assert registry_path.read_text(encoding="utf-8") == before


def test_import_ecc_defaults_disabled(tmp_path: Path) -> None:
    _write_base_config(tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "external_skill_inventory.json").write_text(json.dumps({
        "source": "ecc",
        "agents": [{"id": "ecc.security-reviewer", "name": "security-reviewer", "type": "agent", "capabilities": ["security_review"], "risk_level": "medium"}],
        "skills": [],
    }), encoding="utf-8")
    _run_cli(tmp_path, "import-ecc")
    registry = yaml.safe_load((tmp_path / "config" / "external_skill_registry.yml").read_text(encoding="utf-8"))
    imported = {item["skill_id"]: item for item in registry["external_skills"]}
    assert imported["ecc.security-reviewer"]["enabled"] is False
    assert imported["ecc.security-reviewer"]["integration_mode"] == "inventory_only"
    assert imported["ecc.security-reviewer"]["risk"]["requires_approval"] is True
    assert imported["ecc.security-reviewer"]["license"]["license_review_required"] is True