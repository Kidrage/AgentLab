from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from mcp_server import call_tool, list_tools


def test_external_skill_mcp_tools_are_readonly(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    registry_path = config / "external_skill_registry.yml"
    registry = {
        "schema_version": 1,
        "external_skills": [{"skill_id": "ecc.planner", "source": "ecc", "enabled": False, "license": {"name": "unknown"}}],
    }
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    before = registry_path.read_text(encoding="utf-8")
    tool_names = {tool["name"] for tool in list_tools()}
    assert {"agentlab_list_external_skills", "agentlab_get_skill_registry", "agentlab_get_skill_incubation_candidates"}.issubset(tool_names)
    result = call_tool("agentlab_list_external_skills", {}, agentlab_root=tmp_path)
    assert result["readonly"] is True
    assert result["skills"][0]["enabled"] is False
    call_tool("agentlab_get_skill_registry", {}, agentlab_root=tmp_path)
    call_tool("agentlab_get_skill_incubation_candidates", {}, agentlab_root=tmp_path)
    after = registry_path.read_text(encoding="utf-8")
    assert after == before