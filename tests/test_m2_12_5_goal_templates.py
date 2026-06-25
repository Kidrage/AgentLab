"""Tests for M2-12.5 Goal Templates — completeness and correctness."""

from __future__ import annotations

import pytest

from agent_runtime.goals.templates import (
    TEMPLATES,
    REQUIRED_TEMPLATE_IDS,
    get_template,
)


class TestRequiredTemplates:
    def test_all_required_templates_exist(self):
        for template_id in REQUIRED_TEMPLATE_IDS:
            assert template_id in TEMPLATES, f"{template_id} template is missing"

    def test_no_required_template_has_empty_stages(self):
        for template_id in REQUIRED_TEMPLATE_IDS:
            template = TEMPLATES[template_id]
            stages = template.get("stages") or []
            assert len(stages) > 0, f"{template_id} has empty stages"

    def test_every_stage_has_required_artifacts(self):
        for template_id, template in TEMPLATES.items():
            for stage in template.get("stages", []):
                assert "required_artifacts" in stage, \
                    f"{template_id}/{stage['stage_id']} missing required_artifacts"

    def test_every_stage_has_required_evidence(self):
        for template_id, template in TEMPLATES.items():
            for stage in template.get("stages", []):
                assert "required_evidence" in stage, \
                    f"{template_id}/{stage['stage_id']} missing required_evidence"

    def test_every_stage_has_acceptance_gates(self):
        for template_id, template in TEMPLATES.items():
            for stage in template.get("stages", []):
                assert "acceptance_gates" in stage, \
                    f"{template_id}/{stage['stage_id']} missing acceptance_gates"

    def test_every_stage_has_blocks_m2_closure(self):
        for template_id, template in TEMPLATES.items():
            for stage in template.get("stages", []):
                assert "blocks_m2_closure" in stage, \
                    f"{template_id}/{stage['stage_id']} missing blocks_m2_closure"

    def test_every_stage_has_stage_id(self):
        for template_id, template in TEMPLATES.items():
            for stage in template.get("stages", []):
                assert "stage_id" in stage, \
                    f"{template_id} has stage without stage_id"

    def test_future_reserved_stages_do_not_block_m2_closure(self):
        for template_id, template in TEMPLATES.items():
            for stage in template.get("stages", []):
                if stage.get("status") == "future_reserved":
                    assert stage.get("blocks_m2_closure") is False, \
                        f"{template_id}/{stage['stage_id']} future_reserved must not block M2"

    def test_agentlab_self_repair_includes_governance_kernel(self):
        template = TEMPLATES["agentlab_self_repair"]
        stage_ids = [s["stage_id"] for s in template["stages"]]
        assert "governance_kernel" in stage_ids

    def test_agentlab_self_repair_includes_operator_os(self):
        template = TEMPLATES["agentlab_self_repair"]
        stage_ids = [s["stage_id"] for s in template["stages"]]
        assert "operator_os_bridge" in stage_ids

    def test_agentlab_self_repair_includes_p2r_os_future(self):
        template = TEMPLATES["agentlab_self_repair"]
        stage_ids = [s["stage_id"] for s in template["stages"]]
        assert "p2r_os_future" in stage_ids

    def test_operator_os_goal_management_exists(self):
        assert "operator_os_goal_management" in TEMPLATES

    def test_operator_os_goal_management_has_all_goal_actions(self):
        template = TEMPLATES["operator_os_goal_management"]
        stage_ids = [s["stage_id"] for s in template["stages"]]
        expected = ["goal_set_stage", "goal_plan_stage", "goal_progress_stage",
                     "goal_validate_stage", "goal_report_stage"]
        for s in expected:
            assert s in stage_ids, f"Missing stage {s} in operator_os_goal_management"

    def test_unknown_large_project_has_stage(self):
        template = TEMPLATES["unknown_large_project"]
        assert len(template.get("stages", [])) >= 1

    def test_get_template_returns_none_for_missing(self):
        assert get_template("nonexistent_template") is None

    def test_get_template_returns_template_for_valid(self):
        template = get_template("codebase_build")
        assert template is not None
        assert template["template_id"] == "codebase_build"
