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


def test_mcp_incubation_candidates_readonly(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    registry_path = config / "external_skill_registry.yml"
    registry_path.write_text(yaml.safe_dump({
        "schema_version": 1,
        "external_skills": [{
            "skill_id": "ecc.planner",
            "source": "ecc",
            "display_name": "ECC Planner",
            "integration_mode": "inventory_only",
            "enabled": False,
            "capabilities": ["planning"],
            "suitable_task_types": ["repo_patch"],
            "risk": {"level": "medium", "reasons": ["external_dependency_risk"], "requires_approval": True},
            "license": {"name": "unknown", "license_review_required": True},
        }],
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
    run_dir = tmp_path / "projects" / "AgentLab" / "runs" / "task_mcp"
    run_dir.mkdir(parents=True)
    (run_dir / "skill_usage_ledger.yml").write_text(yaml.safe_dump({"entries": [
        {"skill_id": "ecc.planner", "event": "used", "success": True, "quality_score": 0.9},
        {"skill_id": "ecc.planner", "event": "used", "success": True, "quality_score": 0.9},
    ]}), encoding="utf-8")
    before = registry_path.read_text(encoding="utf-8")
    result = call_tool("agentlab_get_skill_incubation_candidates", {"task_id": "task_mcp", "project": "AgentLab"}, agentlab_root=tmp_path)
    assert result["readonly"] is True
    assert result["source"] == "computed_in_memory"
    assert result["candidates"]
    assert not (run_dir / "artifacts" / "internal_skill_candidates.yml").exists()
    assert registry_path.read_text(encoding="utf-8") == before


def test_mcp_incubation_candidates_prefers_file_and_redacts_absolute_paths(tmp_path: Path) -> None:
    artifacts = tmp_path / "projects" / "AgentLab" / "runs" / "task_file" / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "internal_skill_candidates.yml").write_text(yaml.safe_dump({
        "candidates": [{"candidate_id": "internal.x", "proposed_internal_skill": {"target_path": str(tmp_path / "skills" / "internal" / "x" / "SKILL.md")}}]
    }), encoding="utf-8")
    result = call_tool("agentlab_get_skill_incubation_candidates", {"task_id": "task_file", "project": "AgentLab"}, agentlab_root=tmp_path)
    assert result["source"] == "file"
    target = result["candidates"]["candidates"][0]["proposed_internal_skill"]["target_path"]
    assert str(tmp_path) not in target