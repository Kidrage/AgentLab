from agent_runtime.goals.templates import select_template

def test_agentlab_self_repair_template_selection():
    t = select_template("Repair AgentLab M2 mainline")
    assert t["template_id"] == "agentlab_self_repair"

def test_novel_longform_selection():
    t = select_template("write a novel")
    assert t["template_id"] == "longform_creation"

def test_research_archive_selection():
    t = select_template("research paper")
    assert t["template_id"] == "research_archive"

def test_video_generation_selection():
    t = select_template("make short drama video")
    assert t["template_id"] == "video_generation"

def test_unknown_large_project_selection():
    t = select_template("something completely different")
    assert t["template_id"] == "unknown_large_project"

def test_every_stage_has_required_fields():
    from agent_runtime.goals.templates import TEMPLATES
    for k, v in TEMPLATES.items():
        for s in v.get("stages", []):
            assert "required_artifacts" in s
            assert "required_evidence" in s
            assert "acceptance_gates" in s

def test_m3_future_reserved_does_not_block_m2_closure():
    from agent_runtime.goals.templates import TEMPLATES
    m3 = next(s for s in TEMPLATES["agentlab_self_repair"]["stages"] if s["stage_id"] == "m3_revenue")
    assert m3["status"] == "future_reserved"
    assert m3["blocks_m2_closure"] is False
