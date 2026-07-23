from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from external_skills_cli import main


def test_scan_ecc_missing_path_writes_inventory_warning(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "external_skill_registry.yml").write_text("external_skills: []\n", encoding="utf-8")
    (config / "ecc_integration.yml").write_text(yaml.safe_dump({
        "ecc": {
            "enabled": False,
            "mode": "inventory_only",
            "local_paths": [str(tmp_path / "does-not-exist")],
            "scan": {"allow_markdown_scan": True, "allow_json_yaml_scan": True, "max_files": 5, "max_file_kb": 8},
            "import_policy": {"default_enabled": False, "allow_commands": False, "allow_hooks": False, "allow_mcp_servers": False},
        }
    }), encoding="utf-8")
    assert main(["--root", str(tmp_path), "scan-ecc"]) == 0
    inventory_path = (
        tmp_path
        / ".agentlab"
        / "artifacts"
        / "external_skills"
        / "external_skill_inventory.json"
    )
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    assert inventory["found"] is False
    assert inventory["warnings"]


def test_external_inventory_not_written_to_repo_root(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "external_skill_registry.yml").write_text("external_skills: []\n", encoding="utf-8")
    (config / "ecc_integration.yml").write_text(yaml.safe_dump({"ecc": {"enabled": False, "mode": "inventory_only", "local_paths": [str(tmp_path / "missing")], "import_policy": {"default_enabled": False, "allow_commands": False, "allow_hooks": False, "allow_mcp_servers": False}}}), encoding="utf-8")
    assert main(["--root", str(tmp_path), "scan-ecc"]) == 0
    assert not (tmp_path / "external_skill_inventory.json").exists()
    assert (
        tmp_path
        / ".agentlab"
        / "artifacts"
        / "external_skills"
        / "external_skill_inventory.json"
    ).exists()
