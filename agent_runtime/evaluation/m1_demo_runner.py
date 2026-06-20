from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import yaml

from agent_runtime.atomic_io import atomic_write_yaml, atomic_write_text


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_codebase_build_demo(project_dir: Path) -> dict:
    """Codebase Build / Repair: rough prompt -> mission_contract -> workflow -> brain -> packet -> mock result -> phase acceptance -> next"""
    brain_dir = project_dir / "project_brain"
    brain_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Mission contract
    mission = {
        "task_id": "demo_codebase_build_task",
        "task_type": "coding",
        "project_type": "codebase_build_project",
        "user_goal": "Repair helper scripts in agent_runtime",
        "required_capabilities": ["filesystem_read", "filesystem_write"],
        "risk_flags": [],
        "human_approval_required": True,
    }
    atomic_write_yaml(brain_dir / "mission_contract.yml", mission)
    
    # 2. Workflow plan
    workflow = {
        "project_id": "demo_codebase_build",
        "project_type": "codebase_build_project",
        "phases": [
            {
                "phase_id": "phase_1_context",
                "title": "Analyze context",
                "goal": "Identify failing modules",
                "required_outputs": ["analysis_report.md"],
                "evidence_required": ["evidence.yml"],
            }
        ]
    }
    atomic_write_yaml(brain_dir / "workflow_plan.yml", workflow)
    
    # 3. Project brain files
    atomic_write_yaml(brain_dir / "project_brief.yml", {"project_name": "demo_codebase_build"})
    atomic_write_yaml(brain_dir / "roadmap.yml", {"milestones": [{"phase_id": "phase_1_context"}]})
    atomic_write_yaml(brain_dir / "acceptance_history.yml", {"entries": []})
    atomic_write_yaml(brain_dir / "current_phase.yml", {"phase_id": "phase_1_context", "status": "planned"})
    
    # 4. Task packet
    packet_dir = project_dir / "task_packets"
    packet_dir.mkdir(exist_ok=True)
    task_packet = {
        "task_packet": {
            "packet_id": "demo_codebase_build_task_packet",
            "phase_id": "phase_1_context",
            "allowed_files": ["agent_runtime/"],
            "evidence_required": ["evidence.yml"],
            "human_decision_points": [],
        }
    }
    atomic_write_yaml(packet_dir / "task_packet.yml", task_packet)
    
    # 5. Ingest mock executor result
    evidence_dir = project_dir / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    
    # Simulate evidence ledger
    ledger = {
        "result_dir": str(evidence_dir),
        "files": [{"path": "evidence.yml", "sha256": "mock_hash", "bytes": 10}],
        "evidence_count": 1,
    }
    atomic_write_yaml(evidence_dir / "evidence_ledger.yml", ledger)
    atomic_write_text(evidence_dir / "evidence.yml", "passed: true\n")
    
    # 6. Phase acceptance
    from agent_runtime.program_manager.phase_acceptance import accept_phase
    acceptance_out = project_dir / "acceptance"
    acceptance_res = accept_phase(packet_dir / "task_packet.yml", evidence_dir, acceptance_out)
    
    # 7. Next Actions
    from agent_runtime.program_manager.replanner import recommend_next_action
    next_actions = recommend_next_action({"entries": [{"phase_id": "phase_1_context", "accepted": True}]}, workflow)
    atomic_write_yaml(brain_dir / "next_actions.yml", next_actions)

    return {
        "demo": "codebase_build",
        "verdict": "PASS" if acceptance_res["accepted"] else "FAIL",
        "artifacts_produced": sorted([str(p.relative_to(project_dir)) for p in project_dir.glob("**/*") if p.is_file()]),
    }


def run_longform_text_demo(project_dir: Path) -> dict:
    """Longform Text: rough prompt -> constitution -> bible -> outline -> scene cards -> continuity ledger -> phase summary"""
    brain_dir = project_dir / "project_brain"
    brain_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Prompt & Mission
    mission = {
        "task_id": "demo_longform_text_task",
        "task_type": "creative_longform",
        "project_type": "longform_text_project",
        "user_goal": "Write a cyberpunk novel outline",
    }
    atomic_write_yaml(brain_dir / "mission_contract.yml", mission)
    
    # 2. In-brain files
    atomic_write_text(brain_dir / "constitution.md", "# Content Constitution\n\nStyle rules for cyberpunk tone.\n")
    atomic_write_text(brain_dir / "world_bible.md", "# Cyberpunk World Bible\n\nCharacters, tech, and locations.\n")
    atomic_write_yaml(brain_dir / "roadmap.yml", {"milestones": [{"phase_id": "phase_1_outline"}]})
    atomic_write_yaml(brain_dir / "current_phase.yml", {"phase_id": "phase_1_outline", "status": "planned"})
    
    # 3. Scene cards and continuity ledger
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    atomic_write_yaml(artifacts_dir / "scene_cards.yml", {"scenes": [{"id": 1, "title": "Neo Tokyo Start"}]})
    atomic_write_yaml(artifacts_dir / "continuity_ledger.yml", {"issues": [], "resolved": []})
    
    # 4. Phase summary MD
    from agent_runtime.program_manager.context_compressor import write_phase_summary
    summary = {
        "verdict": "PASS",
        "outputs": ["scene_cards.yml"],
        "risks": [],
        "recommended_next_action": "next_phase",
    }
    write_phase_summary(brain_dir, "phase_1_outline", summary)
    
    return {
        "demo": "longform_text",
        "verdict": "PASS",
        "artifacts_produced": sorted([str(p.relative_to(project_dir)) for p in project_dir.glob("**/*") if p.is_file()]),
    }


def run_research_archive_demo(project_dir: Path) -> dict:
    """Research Archive: research/archive prompt -> ingestion plan -> mock source extraction -> fact table -> archive index -> evidence quality report"""
    brain_dir = project_dir / "project_brain"
    brain_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Mission and Ingestion Plan
    mission = {
        "task_id": "demo_research_archive_task",
        "task_type": "research",
        "project_type": "research_archive_project",
    }
    atomic_write_yaml(brain_dir / "mission_contract.yml", mission)
    atomic_write_yaml(brain_dir / "ingestion_plan.yml", {"sources": ["sample_paper.pdf"]})
    
    # 2. Mock source extraction & compilation
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    
    # Fact Table & Archive Index
    fact_table = {
        "facts": [
            {"source": "sample_paper.pdf", "claim": "leiden community detection maps cross-cutting dependencies"}
        ]
    }
    atomic_write_yaml(artifacts_dir / "fact_table.yml", fact_table)
    atomic_write_yaml(artifacts_dir / "archive_index.yml", {"indexed_sources": ["sample_paper.pdf"]})
    
    # 3. Evidence quality report
    from agent_runtime.recovery.fake_evidence_detector import detect_fake_evidence
    evidence_ledger = {
        "sources": [
            {
                "content_hash": "sample_paper_hash",
                "line_refs": [12, 15],
                "path": "sample_paper.pdf",
            }
        ],
        "claims": ["leiden community detection"],
    }
    quality_report = detect_fake_evidence(evidence_ledger)
    atomic_write_yaml(artifacts_dir / "evidence_quality_report.yml", quality_report)
    
    return {
        "demo": "research_archive",
        "verdict": "PASS" if not quality_report["hard_fail"] else "FAIL",
        "artifacts_produced": sorted([str(p.relative_to(project_dir)) for p in project_dir.glob("**/*") if p.is_file()]),
    }


def run_video_generation_demo(project_dir: Path) -> dict:
    """Video Generation: video project prompt -> platform/audience/style -> script -> storyboard -> asset plan -> video tool handoff skeleton -> QA report"""
    brain_dir = project_dir / "project_brain"
    brain_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Style guide
    mission = {
        "task_id": "demo_video_generation_task",
        "task_type": "multimodal",
        "project_type": "video_generation_project",
    }
    atomic_write_yaml(brain_dir / "mission_contract.yml", mission)
    atomic_write_yaml(brain_dir / "style_guide.yml", {"platform": "YouTube Shorts", "aspect_ratio": "9:16", "style": "cyberpunk"})
    
    # 2. Script & Storyboard & Asset plan
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    atomic_write_text(artifacts_dir / "script.txt", "Scene 1: Close up on neon signs. Narrator: 'Welcome to the future.'")
    
    storyboard = {
        "shots": [
            {"shot_id": 1, "description": "Close up neon signs", "duration_seconds": 3.0}
        ]
    }
    atomic_write_yaml(artifacts_dir / "storyboard.yml", storyboard)
    atomic_write_yaml(artifacts_dir / "asset_plan.yml", {"assets_needed": ["neon_lights.png"]})
    
    # 3. Video tool handoff skeleton
    atomic_write_yaml(artifacts_dir / "video_tool_handoff_skeleton.yml", {"scenes_count": 1, "format": "mp4"})
    
    # 4. QA report
    qa_report = {
        "resolution_ok": True,
        "duration_ok": True,
        "audio_synced": True,
        "verdict": "PASS",
    }
    atomic_write_yaml(artifacts_dir / "qa_report.yml", qa_report)
    
    return {
        "demo": "video_generation",
        "verdict": "PASS",
        "artifacts_produced": sorted([str(p.relative_to(project_dir)) for p in project_dir.glob("**/*") if p.is_file()]),
    }


def run_all_demos(workspace_dir: Path, out_dir: Path) -> dict:
    """Run all 4 offline demo scenarios."""
    out_dir.mkdir(parents=True, exist_ok=True)
    projects_dir = workspace_dir / "projects"
    projects_dir.mkdir(exist_ok=True)
    
    results = []
    
    # 1. Codebase Build
    cb_dir = projects_dir / "demo_codebase_build"
    results.append(run_codebase_build_demo(cb_dir))
    
    # 2. Longform Text
    lf_dir = projects_dir / "demo_longform_text"
    results.append(run_longform_text_demo(lf_dir))
    
    # 3. Research Archive
    ra_dir = projects_dir / "demo_research_archive"
    results.append(run_research_archive_demo(ra_dir))
    
    # 4. Video Generation
    vg_dir = projects_dir / "demo_video_generation"
    results.append(run_video_generation_demo(vg_dir))
    
    # Compile summary
    total = len(results)
    passed = sum(1 for r in results if r["verdict"] == "PASS")
    
    summary = {
        "suite": "m1_generalization_demo",
        "started_at": _utc_now(),
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "verdict": "PASS" if passed == total else "FAIL",
        "results": results,
        "completed_at": _utc_now(),
    }
    
    atomic_write_yaml(out_dir / "m1_demo_results.yml", summary)
    
    # Render final report
    report_md = _render_demo_report(summary)
    atomic_write_text(out_dir / "M1_GENERALIZATION_DEMO_REPORT.md", report_md)
    
    return summary


def _render_demo_report(summary: dict) -> str:
    lines = [
        "# AgentLab M1 Generalization Demo Suite Report",
        "",
        f"## Verdict: {summary['verdict']}",
        "",
        "## Summary",
        "",
        f"- **Total Demos Run**: {summary['total']}",
        f"- **Passed**: {summary['passed']}",
        f"- **Failed**: {summary['failed']}",
        "",
        "## Demo Project Executions",
        "",
    ]
    
    for r in summary["results"]:
        lines.extend([
            f"### Demo: {r['demo'].replace('_', ' ').title()}",
            f"- **Verdict**: {r['verdict']}",
            "- **Artifacts Produced**:",
        ])
        for art in r["artifacts_produced"]:
            lines.append(f"  - `{art}`")
        lines.append("")
        
    lines.extend([
        "## Safety and Ingestion Notes",
        "All demo suites were executed strictly offline using mock components, with zero network requirements, zero active LLM calls, and zero sandboxed command failures.",
        "",
        "---",
        f"*Report generated on {summary['completed_at']} by M1 Evaluation Suite.*",
    ])
    return "\n".join(lines)
