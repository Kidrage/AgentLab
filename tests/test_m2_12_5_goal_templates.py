"""Tests for M2-12.5 Goal Templates — completeness and correctness."""

from agent_runtime.goals.templates import TEMPLATES, REQUIRED_TEMPLATE_IDS, select_template


class TestRequiredTemplates:
    def test_all_required_templates_exist(self):
        for template_id in REQUIRED_TEMPLATE_IDS:
            assert template_id in TEMPLATES, f"{template_id} template is missing"

    def test_no_required_template_has_empty_stages(self):
        for template_id in REQUIRED_TEMPLATE_IDS:
            stages = TEMPLATES[template_id].get("stages", [])
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

    def test_select_template_returns_agentlab_for_agentlab_keywords(self):
        template = select_template("Repair AgentLab mainline")
        assert template["template_id"] == "agentlab_self_repair"

    def test_select_template_returns_codebase_for_codebase_keywords(self):
        template = select_template("Build a new software app")
        assert template["template_id"] == "codebase_build"

    def test_select_template_returns_longform_for_novel_keywords(self):
        template = select_template("Write a science fiction novel")
        assert template["template_id"] == "longform_creation"

    def test_select_template_returns_research_for_research_keywords(self):
        template = select_template("Conduct a research paper review")
        assert template["template_id"] == "research_archive"

    def test_select_template_returns_unknown_for_non_matching(self):
        template = select_template("xyzzy foobar blarg")
        assert template["template_id"] == "unknown_large_project"
