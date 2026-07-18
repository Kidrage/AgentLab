"""Creative writing route lifecycle node coverage."""

import sys
from pathlib import Path

import yaml

AGENT_RUNTIME = Path(__file__).resolve().parents[1] / "agent_runtime"
if str(AGENT_RUNTIME) not in sys.path:
    sys.path.insert(0, str(AGENT_RUNTIME))

from agent_runtime.lifecycle_graph import NODE_REQUIRED_OUTPUTS, create_lifecycle, load_lifecycle, save_lifecycle
from agent_runtime.pipeline_runner import NODE_TO_AGENT, NODE_TO_REPORT, _ensure_lifecycle_shape, run_next_node
from agent_runtime.agent_runner import DEFAULT_REPORT_BY_AGENT


def test_fiction_route_enables_writer_reviewer_scribe_nodes(tmp_path: Path):
    workflow = {
        "route": {
            "agents": ["Supervisor", "Writer", "Reviewer", "Scribe", "Verifier", "Archivist"],
        },
    }

    lifecycle = create_lifecycle(tmp_path, workflow)

    assert lifecycle["nodes"]["ARTIFACT_PRODUCTION"]["status"] == "skipped"
    assert lifecycle["nodes"]["ARTIFACT_PRODUCTION"]["skip_reason"] == "Route does not include ArtifactProducer"
    assert lifecycle["nodes"]["WRITER_DRAFT"]["status"] == "waiting"
    assert lifecycle["nodes"]["FICTION_REVIEW"]["status"] == "waiting"
    assert lifecycle["nodes"]["SCRIBE_LEDGER"]["status"] == "waiting"
    assert NODE_REQUIRED_OUTPUTS["WRITER_DRAFT"] == ["fiction_draft.md"]
    assert NODE_REQUIRED_OUTPUTS["FICTION_REVIEW"] == ["fiction_review.yml"]
    assert NODE_REQUIRED_OUTPUTS["SCRIBE_LEDGER"] == ["continuity_ledger.yml"]
    assert NODE_TO_AGENT["WRITER_DRAFT"] == "Writer"
    assert NODE_TO_AGENT["FICTION_REVIEW"] == "Reviewer"
    assert NODE_TO_AGENT["SCRIBE_LEDGER"] == "Scribe"
    assert NODE_TO_REPORT["WRITER_DRAFT"] == "fiction_draft.md"
    assert NODE_TO_REPORT["FICTION_REVIEW"] == "fiction_review.yml"
    assert NODE_TO_REPORT["SCRIBE_LEDGER"] == "continuity_ledger.yml"


def test_narrative_rewrite_planner_has_independent_lifecycle_node():
    assert NODE_REQUIRED_OUTPUTS["NARRATIVE_REWRITE_PLAN"] == [
        "chapter_state_plan.yml"
    ]
    assert NODE_TO_AGENT["NARRATIVE_REWRITE_PLAN"] == "NarrativePlanner"
    assert NODE_TO_REPORT["NARRATIVE_REWRITE_PLAN"] == "chapter_state_plan.yml"


def test_narrative_light_route_skips_heavy_lifecycle_nodes(tmp_path: Path):
    workflow = {
        "route": {
            "agents": ["Supervisor", "Writer"],
        },
    }

    lifecycle = create_lifecycle(tmp_path, workflow)

    assert lifecycle["nodes"]["WRITER_DRAFT"]["status"] == "waiting"
    for node_id, agent_name in {
        "FICTION_REVIEW": "Reviewer",
        "SCRIBE_LEDGER": "Scribe",
        "VALIDATION": "TesterAuditor",
        "AUDIT": "TesterAuditor",
        "VERIFY": "Verifier",
        "ARCHIVE": "Archivist",
    }.items():
        assert lifecycle["nodes"][node_id]["status"] == "skipped", node_id
        assert lifecycle["nodes"][node_id]["skip_reason"] == f"Route does not include {agent_name}"


def test_heavy_audit_route_requires_complete_four_file_delivery() -> None:
    from agent_runtime.artifact_contract import (
        _required_artifacts_for_run,
        _route_required_outputs,
    )

    workflow = {
        "route": {
            "route_key": "narrative_heavy_audit",
            "agents": ["Supervisor", "Reviewer", "Scribe", "Verifier"],
        }
    }
    expected = [
        "fiction_review.yml",
        "continuity_failure_report.yml",
        "state_transition_proposal.yml",
        "revision_or_rewrite_proposal.yml",
    ]
    assert _route_required_outputs(workflow) == expected
    required = _required_artifacts_for_run(Path("/nonexistent"), workflow["route"]["agents"], workflow)
    assert "verification_report.md" not in required
    for name in expected:
        assert name in required


def test_narrative_production_pack_excludes_code_shell_nodes(tmp_path: Path):
    workflow = {
        "route": {
            "agents": ["Supervisor", "Writer"],
        },
        "production_pack": {
            "pack_id": "narrative_longform",
            "lifecycle_nodes": [
                "INIT_TASK",
                "CONTEXT_PROFILE",
                "CONTEXT_BUDGET",
                "CONTEXT_PACK",
                "PREPARE_PLAN",
                "SUPERVISOR_PLAN",
                "WRITER_DRAFT",
                "SELF_CHECK",
                "FINALIZE",
            ],
        },
    }

    lifecycle = create_lifecycle(tmp_path, workflow)

    assert lifecycle["nodes"]["WRITER_DRAFT"]["status"] == "waiting"
    for node_id in {"REPO_CONTEXT", "INTERFACE_OPTIONAL", "CODER_IMPLEMENTATION"}:
        assert lifecycle["nodes"][node_id]["status"] == "skipped", node_id
        assert lifecycle["nodes"][node_id]["skip_reason"] == (
            f"Production pack narrative_longform excludes {node_id}"
        )


def test_article_light_route_skips_code_and_heavy_lifecycle_nodes(tmp_path: Path):
    workflow = {
        "route": {
            "agents": ["Supervisor", "ArtifactProducer"],
        },
    }

    lifecycle = create_lifecycle(tmp_path, workflow)

    assert lifecycle["nodes"]["ARTIFACT_PRODUCTION"]["status"] == "waiting"
    assert NODE_REQUIRED_OUTPUTS["ARTIFACT_PRODUCTION"] == ["artifact_producer_report.md"]
    assert NODE_TO_AGENT["ARTIFACT_PRODUCTION"] == "ArtifactProducer"
    assert NODE_TO_REPORT["ARTIFACT_PRODUCTION"] == "artifact_producer_report.md"
    for node_id, agent_name in {
        "WRITER_DRAFT": "Writer",
        "FICTION_REVIEW": "Reviewer",
        "SCRIBE_LEDGER": "Scribe",
        "CODER_IMPLEMENTATION": "Coder",
        "VALIDATION": "TesterAuditor",
        "AUDIT": "TesterAuditor",
        "VERIFY": "Verifier",
        "ARCHIVE": "Archivist",
    }.items():
        assert lifecycle["nodes"][node_id]["status"] == "skipped", node_id
        assert lifecycle["nodes"][node_id]["skip_reason"] == f"Route does not include {agent_name}"


def test_article_production_pack_excludes_repo_context(tmp_path: Path):
    workflow = {
        "route": {
            "agents": ["Supervisor", "ArtifactProducer"],
        },
        "production_pack": {
            "pack_id": "article_light",
            "lifecycle_nodes": [
                "INIT_TASK",
                "CONTEXT_PROFILE",
                "CONTEXT_BUDGET",
                "CONTEXT_PACK",
                "PREPARE_PLAN",
                "SUPERVISOR_PLAN",
                "ARTIFACT_PRODUCTION",
                "SELF_CHECK",
                "FINALIZE",
            ],
        },
    }

    lifecycle = create_lifecycle(tmp_path, workflow)

    assert lifecycle["nodes"]["ARTIFACT_PRODUCTION"]["status"] == "waiting"
    assert lifecycle["nodes"]["REPO_CONTEXT"]["status"] == "skipped"
    assert lifecycle["nodes"]["REPO_CONTEXT"]["skip_reason"] == (
        "Production pack article_light excludes REPO_CONTEXT"
    )


def test_media_series_production_pack_excludes_archive_until_acceptance(tmp_path: Path):
    workflow = {
        "route": {
            "agents": ["Supervisor", "ArtifactProducer", "TesterAuditor", "Verifier", "Archivist"],
        },
        "production_pack": {
            "pack_id": "media_series_production",
            "lifecycle_nodes": [
                "INIT_TASK",
                "CONTEXT_PROFILE",
                "CONTEXT_BUDGET",
                "CONTEXT_PACK",
                "PREPARE_PLAN",
                "SUPERVISOR_PLAN",
                "ARTIFACT_PRODUCTION",
                "VALIDATION",
                "VERIFY",
                "SELF_CHECK",
                "FINALIZE",
            ],
        },
    }

    lifecycle = create_lifecycle(tmp_path, workflow)

    assert lifecycle["nodes"]["ARTIFACT_PRODUCTION"]["status"] == "waiting"
    assert lifecycle["nodes"]["ARCHIVE"]["status"] == "skipped"
    assert lifecycle["nodes"]["ARCHIVE"]["skip_reason"] == (
        "Production pack media_series_production excludes ARCHIVE"
    )


def test_lifecycle_shape_repair_respects_production_pack_excluded_nodes(tmp_path: Path):
    workflow_plan = (
        "route:\n"
        "  agents:\n"
        "    - Supervisor\n"
        "    - ArtifactProducer\n"
        "    - TesterAuditor\n"
        "    - Verifier\n"
        "    - Archivist\n"
        "production_pack:\n"
        "  pack_id: media_series_production\n"
        "  lifecycle_nodes:\n"
        "    - INIT_TASK\n"
        "    - CONTEXT_PROFILE\n"
        "    - CONTEXT_BUDGET\n"
        "    - CONTEXT_PACK\n"
        "    - PREPARE_PLAN\n"
        "    - SUPERVISOR_PLAN\n"
        "    - ARTIFACT_PRODUCTION\n"
        "    - VALIDATION\n"
        "    - VERIFY\n"
        "    - SELF_CHECK\n"
        "    - FINALIZE\n"
    )
    (tmp_path / "workflow_plan.yml").write_text(workflow_plan, encoding="utf-8")
    lifecycle = create_lifecycle(
        tmp_path,
        {
            "route": {
                "agents": ["Supervisor", "ArtifactProducer", "TesterAuditor", "Verifier", "Archivist"],
            },
            "production_pack": {
                "pack_id": "media_series_production",
                "lifecycle_nodes": [
                    "INIT_TASK",
                    "CONTEXT_PROFILE",
                    "CONTEXT_BUDGET",
                    "CONTEXT_PACK",
                    "PREPARE_PLAN",
                    "SUPERVISOR_PLAN",
                    "ARTIFACT_PRODUCTION",
                    "VALIDATION",
                    "VERIFY",
                    "SELF_CHECK",
                    "FINALIZE",
                ],
            },
        },
    )
    del lifecycle["nodes"]["ARCHIVE"]
    save_lifecycle(tmp_path, lifecycle)

    _ensure_lifecycle_shape(tmp_path)

    repaired = load_lifecycle(tmp_path)
    assert repaired["nodes"]["ARCHIVE"]["status"] == "skipped"
    assert repaired["nodes"]["ARCHIVE"]["skip_reason"] == (
        "Production pack media_series_production excludes ARCHIVE"
    )


def test_prepare_plan_does_not_revive_production_pack_excluded_nodes(tmp_path: Path):
    root = tmp_path
    run_dir = root / "projects" / "Demo" / "runs" / "task_media_prepare"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text("media task\n", encoding="utf-8")
    workflow_plan = (
        "route:\n"
        "  agents:\n"
        "    - Supervisor\n"
        "    - ArtifactProducer\n"
        "    - TesterAuditor\n"
        "    - Verifier\n"
        "    - Archivist\n"
        "production_pack:\n"
        "  pack_id: media_series_production\n"
        "  lifecycle_nodes:\n"
        "    - INIT_TASK\n"
        "    - CONTEXT_PROFILE\n"
        "    - CONTEXT_BUDGET\n"
        "    - CONTEXT_PACK\n"
        "    - PREPARE_PLAN\n"
        "    - SUPERVISOR_PLAN\n"
        "    - ARTIFACT_PRODUCTION\n"
        "    - VALIDATION\n"
        "    - VERIFY\n"
        "    - SELF_CHECK\n"
        "    - FINALIZE\n"
    )
    (run_dir / "workflow_plan.yml").write_text(workflow_plan, encoding="utf-8")
    lifecycle = create_lifecycle(
        run_dir,
        {
            "route": {
                "agents": ["Supervisor", "ArtifactProducer", "TesterAuditor", "Verifier", "Archivist"],
            },
            "production_pack": {
                "pack_id": "media_series_production",
                "lifecycle_nodes": [
                    "INIT_TASK",
                    "CONTEXT_PROFILE",
                    "CONTEXT_BUDGET",
                    "CONTEXT_PACK",
                    "PREPARE_PLAN",
                    "SUPERVISOR_PLAN",
                    "ARTIFACT_PRODUCTION",
                    "VALIDATION",
                    "VERIFY",
                    "SELF_CHECK",
                    "FINALIZE",
                ],
            },
        },
    )
    for node_id in ["INIT_TASK", "CONTEXT_PROFILE", "CONTEXT_BUDGET", "CONTEXT_PACK"]:
        lifecycle["nodes"][node_id]["status"] = "completed"
    save_lifecycle(run_dir, lifecycle)

    result = run_next_node(root, "Demo", "task_media_prepare", fake_provider=True)

    assert result["node"] == "PREPARE_PLAN"
    repaired = load_lifecycle(run_dir)
    assert repaired["nodes"]["ARCHIVE"]["status"] == "skipped"
    assert repaired["nodes"]["ARCHIVE"]["skip_reason"] == (
        "Production pack media_series_production excludes ARCHIVE"
    )
    mission = yaml.safe_load(
        (run_dir / "mission_contract.yml").read_text(encoding="utf-8")
    )
    assert mission["task_id"] == "task_media_prepare"
    assert mission["compiler_source"] == "rule_based"


def test_pack_synthesis_research_node_writes_domain_brief(tmp_path: Path):
    root = tmp_path
    run_dir = root / "projects" / "Demo" / "runs" / "task_pack_synthesis"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text("design a new immersive production pack\n", encoding="utf-8")
    (run_dir / "workflow_plan.yml").write_text(
        "route:\n"
        "  agents:\n"
        "    - Supervisor\n"
        "    - Researcher\n"
        "    - ArtifactProducer\n"
        "    - Verifier\n"
        "production_pack:\n"
        "  status: synthesis_candidate\n"
        "  pack_id: pack_synthesis_candidate\n"
        "  task_domain: multimodal_asset_generation\n"
        "  artifact_type: installation_show_control\n"
        "  lifecycle_nodes:\n"
        "    - INIT_TASK\n"
        "    - CONTEXT_PROFILE\n"
        "    - CONTEXT_BUDGET\n"
        "    - CONTEXT_PACK\n"
        "    - PREPARE_PLAN\n"
        "    - SUPERVISOR_PLAN\n"
        "    - RESEARCH_OPTIONAL\n"
        "    - ARTIFACT_PRODUCTION\n"
        "    - VERIFY\n"
        "    - SELF_CHECK\n"
        "    - FINALIZE\n",
        encoding="utf-8",
    )
    lifecycle = create_lifecycle(
        run_dir,
        {
            "route": {"agents": ["Supervisor", "Researcher", "ArtifactProducer", "Verifier"]},
            "production_pack": {
                "status": "synthesis_candidate",
                "pack_id": "pack_synthesis_candidate",
                "task_domain": "multimodal_asset_generation",
                "artifact_type": "installation_show_control",
                "lifecycle_nodes": [
                    "INIT_TASK",
                    "CONTEXT_PROFILE",
                    "CONTEXT_BUDGET",
                    "CONTEXT_PACK",
                    "PREPARE_PLAN",
                    "SUPERVISOR_PLAN",
                    "RESEARCH_OPTIONAL",
                    "ARTIFACT_PRODUCTION",
                    "VERIFY",
                    "SELF_CHECK",
                    "FINALIZE",
                ],
            },
        },
    )
    for node_id in ["INIT_TASK", "CONTEXT_PROFILE", "CONTEXT_BUDGET", "CONTEXT_PACK", "PREPARE_PLAN", "SUPERVISOR_PLAN"]:
        lifecycle["nodes"][node_id]["status"] = "completed"
    save_lifecycle(run_dir, lifecycle)

    result = run_next_node(root, "Demo", "task_pack_synthesis", fake_provider=True)

    assert result["node"] == "RESEARCH_OPTIONAL"
    assert result["synthesis_research_output"] == "domain_research_brief.md"
    brief = (run_dir / "domain_research_brief.md").read_text(encoding="utf-8")
    assert "Domain Research Brief" in brief
    assert "multimodal_asset_generation" in brief
    assert "installation_show_control" in brief


def test_nonfiction_route_skips_writer_reviewer_scribe_nodes(tmp_path: Path):
    workflow = {
        "route": {
            "agents": ["Supervisor", "RepoScout", "Coder", "TesterAuditor", "Archivist"],
        },
    }

    lifecycle = create_lifecycle(tmp_path, workflow)

    assert lifecycle["nodes"]["ARTIFACT_PRODUCTION"]["status"] == "skipped"
    assert lifecycle["nodes"]["ARTIFACT_PRODUCTION"]["skip_reason"] == "Route does not include ArtifactProducer"
    assert lifecycle["nodes"]["WRITER_DRAFT"]["status"] == "skipped"
    assert lifecycle["nodes"]["WRITER_DRAFT"]["skip_reason"] == "Route does not include Writer"
    assert lifecycle["nodes"]["FICTION_REVIEW"]["status"] == "skipped"
    assert lifecycle["nodes"]["FICTION_REVIEW"]["skip_reason"] == "Route does not include Reviewer"
    assert lifecycle["nodes"]["SCRIBE_LEDGER"]["status"] == "skipped"
    assert lifecycle["nodes"]["SCRIBE_LEDGER"]["skip_reason"] == "Route does not include Scribe"


def test_lifecycle_node_reports_match_agent_report_contracts():
    nodes_by_agent = {}
    for node_id, agent_name in NODE_TO_AGENT.items():
        nodes_by_agent.setdefault(agent_name, []).append(node_id)
        if node_id in NODE_REQUIRED_OUTPUTS:
            assert NODE_TO_REPORT[node_id] in NODE_REQUIRED_OUTPUTS[node_id], node_id
            if len(NODE_REQUIRED_OUTPUTS[node_id]) == 1:
                assert NODE_REQUIRED_OUTPUTS[node_id] == [NODE_TO_REPORT[node_id]], node_id

    for agent_name, node_ids in nodes_by_agent.items():
        if agent_name in DEFAULT_REPORT_BY_AGENT and len(node_ids) == 1:
            node_id = node_ids[0]
            assert NODE_TO_REPORT[node_id] == DEFAULT_REPORT_BY_AGENT[agent_name], node_id

    assert {NODE_TO_REPORT["VALIDATION"], NODE_TO_REPORT["AUDIT"]} == {
        "07_validation_report.md",
        "08_audit_report.md",
    }
    assert DEFAULT_REPORT_BY_AGENT["TesterAuditor"] in {
        NODE_TO_REPORT["VALIDATION"],
        NODE_TO_REPORT["AUDIT"],
    }
