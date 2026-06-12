from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from external_agents.ecc_inventory import scan_ecc_inventory


def _config(ecc_path: Path, *, max_file_kb: int = 256) -> dict:
    return {
        "ecc": {
            "local_paths": [str(ecc_path)],
            "scan": {"allow_markdown_scan": True, "allow_json_yaml_scan": True, "max_files": 200, "max_file_kb": max_file_kb},
            "risk_defaults": {"level": "medium", "requires_approval": True},
        }
    }


def test_ecc_inventory_missing_path_returns_warning(tmp_path: Path) -> None:
    inventory = scan_ecc_inventory(tmp_path, _config(tmp_path / "missing"))
    assert inventory["found"] is False
    assert inventory["warnings"]


def test_ecc_inventory_scans_agents_md_fixture(tmp_path: Path) -> None:
    ecc = tmp_path / "ECC"
    ecc.mkdir()
    (ecc / "AGENTS.md").write_text("""# Agents

## planner
Plans repo strategy and task decomposition.

## code-reviewer
Reviews code patches.

## security-reviewer
Performs security vulnerability review.
""", encoding="utf-8")
    inventory = scan_ecc_inventory(tmp_path, _config(ecc))
    ids = {agent["id"] for agent in inventory["agents"]}
    assert {"ecc.planner", "ecc.code-reviewer", "ecc.security-reviewer"}.issubset(ids)
    assert all(agent["enabled_by_default"] is False for agent in inventory["agents"])


def test_ecc_inventory_does_not_execute_scripts(tmp_path: Path) -> None:
    ecc = tmp_path / "ECC"
    (ecc / "commands").mkdir(parents=True)
    marker = tmp_path / "executed.txt"
    (ecc / "commands" / "danger.sh").write_text(f"#!/bin/sh\necho owned > {marker}\n", encoding="utf-8")
    inventory = scan_ecc_inventory(tmp_path, _config(ecc))
    assert marker.exists() is False
    assert inventory["commands"][0]["executed"] is False


def test_ecc_inventory_respects_file_size_limit(tmp_path: Path) -> None:
    ecc = tmp_path / "ECC"
    ecc.mkdir()
    (ecc / "AGENTS.md").write_text("x" * 2048, encoding="utf-8")
    inventory = scan_ecc_inventory(tmp_path, _config(ecc, max_file_kb=1))
    assert inventory["agents"] == []
    assert any("exceeds" in warning for warning in inventory["warnings"])
