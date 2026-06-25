"""Goal templates for M2-12.5 Goal/Mainline Command Bridge.

Every template has at least one deterministic stage with required_artifacts,
required_evidence, acceptance_gates, and blocks_m2_closure.

Future-reserved M3 stages have status="future_reserved" and blocks_m2_closure=False.
"""

from __future__ import annotations

from typing import Any

TEMPLATES: dict[str, dict[str, Any]] = {
    "agentlab_self_repair": {
        "template_id": "agentlab_self_repair",
        "display_name": "AgentLab Self-Repair",
        "description": "Self-maintenance, repair, and governance of the AgentLab system itself",
        "mainline_series": [
            "project_governance_kernel",
            "operator_os",
            "p2r_os_future",
        ],
        "stages": [
            {
                "stage_id": "governance_kernel",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": ["goal_contract.yml", "mainline_program.yml"],
                "required_evidence": ["operator_demo_report", "goal_contract.yml"],
                "acceptance_gates": ["demo_passed", "contract_valid"],
            },
            {
                "stage_id": "operator_os_bridge",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": [
                    "mainline_progress.yml",
                    "mainline_acceptance_contract.yml",
                ],
                "required_evidence": ["acceptance_history.yml"],
                "acceptance_gates": ["acceptance_recorded", "progress_updated"],
            },
            {
                "stage_id": "p2r_os_future",
                "status": "future_reserved",
                "blocks_m2_closure": False,
                "required_artifacts": [],
                "required_evidence": [],
                "acceptance_gates": [],
            },
        ],
        "scenario_validations": ["agentlab_self_repair"],
        "future_reserved_stages": ["p2r_os_future"],
    },
    "operator_os_goal_management": {
        "template_id": "operator_os_goal_management",
        "display_name": "Operator OS Goal Management",
        "description": "Project goal setting, planning, validation, and reporting via operator control plane",
        "mainline_series": ["goal_set", "goal_plan", "goal_progress", "goal_validate", "goal_report"],
        "stages": [
            {
                "stage_id": "goal_set_stage",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": ["goal_contract.yml"],
                "required_evidence": ["goal_contract.yml"],
                "acceptance_gates": ["goal_contract_created"],
            },
            {
                "stage_id": "goal_plan_stage",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": [
                    "mission_contract.yml",
                    "workflow_plan.yml",
                    "mainline_program.yml",
                    "mainline_acceptance_contract.yml",
                    "scenario_validation_plan.yml",
                ],
                "required_evidence": [
                    "goal_contract.yml",
                    "mainline_program.yml",
                ],
                "acceptance_gates": ["plan_artifacts_complete"],
            },
            {
                "stage_id": "goal_progress_stage",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": ["mainline_progress.yml", "decision_log.yml"],
                "required_evidence": ["mainline_progress.yml"],
                "acceptance_gates": ["progress_recorded"],
            },
            {
                "stage_id": "goal_validate_stage",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": ["acceptance_history.yml"],
                "required_evidence": [
                    "operator_demo_report",
                    "mainline_progress.yml",
                ],
                "acceptance_gates": ["all_evidence_present", "all_artifacts_present"],
            },
            {
                "stage_id": "goal_report_stage",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": ["mainline_completion_report.md"],
                "required_evidence": ["acceptance_history.yml"],
                "acceptance_gates": ["report_generated"],
            },
        ],
        "scenario_validations": ["operator_os_goal_management"],
        "future_reserved_stages": [],
    },
    "codebase_build": {
        "template_id": "codebase_build",
        "display_name": "Codebase Build",
        "description": "Build software projects — CLI apps, APIs, libraries, or full-stack applications",
        "mainline_series": ["architecture", "implementation", "testing", "delivery"],
        "stages": [
            {
                "stage_id": "codebase_plan",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": [
                    "goal_contract.yml",
                    "mainline_program.yml",
                    "architecture_state.yml",
                ],
                "required_evidence": ["scenario_validation_plan.yml"],
                "acceptance_gates": ["architecture_defined", "contract_valid"],
            },
            {
                "stage_id": "codebase_implement",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": ["mainline_progress.yml", "phase_plan.yml"],
                "required_evidence": ["implementation_evidence"],
                "acceptance_gates": ["code_compiles", "tests_exist"],
            },
        ],
        "scenario_validations": ["codebase_build"],
        "future_reserved_stages": [],
    },
    "longform_creation": {
        "template_id": "longform_creation",
        "display_name": "Longform Creation",
        "description": "Create longform novels or stories with worldbuilding and continuity tracking",
        "mainline_series": ["planning", "drafting", "continuity_review", "delivery"],
        "stages": [
            {
                "stage_id": "longform_plan",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": ["goal_contract.yml", "mainline_program.yml"],
                "required_evidence": ["scenario_validation_plan.yml"],
                "acceptance_gates": ["scenario_validation_present"],
            },
            {
                "stage_id": "longform_continuity",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": ["mainline_progress.yml"],
                "required_evidence": ["continuity_check"],
                "acceptance_gates": ["continuity_gate"],
            },
        ],
        "scenario_validations": ["longform_creation"],
        "future_reserved_stages": [],
    },
    "research_archive": {
        "template_id": "research_archive",
        "display_name": "Research Archive",
        "description": "Conduct systematic research and produce cited reports",
        "mainline_series": ["literature_search", "paper_ingestion", "synthesis", "report"],
        "stages": [
            {
                "stage_id": "research_literature",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": [
                    "goal_contract.yml",
                    "mainline_program.yml",
                    "research_brief.yml",
                ],
                "required_evidence": ["scenario_validation_plan.yml"],
                "acceptance_gates": ["research_brief_created"],
            },
            {
                "stage_id": "research_synthesis",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": ["mainline_progress.yml"],
                "required_evidence": ["citation_ledger"],
                "acceptance_gates": ["synthesis_complete", "citations_tracked"],
            },
        ],
        "scenario_validations": ["research_archive"],
        "future_reserved_stages": [],
    },
    "video_generation": {
        "template_id": "video_generation",
        "display_name": "Video Generation",
        "description": "Plan and produce video content — scripts, storyboards, asset plans",
        "mainline_series": ["scripting", "storyboarding", "production", "post_production"],
        "stages": [
            {
                "stage_id": "video_script",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": ["goal_contract.yml", "mainline_program.yml"],
                "required_evidence": ["scenario_validation_plan.yml"],
                "acceptance_gates": ["script_complete", "scenario_validated"],
            },
            {
                "stage_id": "video_storyboard",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": ["mainline_progress.yml"],
                "required_evidence": ["storyboard_plan"],
                "acceptance_gates": ["storyboard_approved"],
            },
        ],
        "scenario_validations": ["video_generation"],
        "future_reserved_stages": [],
    },
    "document_knowledgebase": {
        "template_id": "document_knowledgebase",
        "display_name": "Document Knowledgebase",
        "description": "Ingest, index, and make searchable a collection of documents",
        "mainline_series": ["ingestion", "extraction", "indexing", "search"],
        "stages": [
            {
                "stage_id": "kb_ingest",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": [
                    "goal_contract.yml",
                    "mainline_program.yml",
                    "repo_manifest.yml",
                ],
                "required_evidence": ["scenario_validation_plan.yml"],
                "acceptance_gates": ["ingestion_complete"],
            },
            {
                "stage_id": "kb_index",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": ["mainline_progress.yml"],
                "required_evidence": ["index_evidence"],
                "acceptance_gates": ["index_built", "search_verified"],
            },
        ],
        "scenario_validations": ["document_knowledgebase"],
        "future_reserved_stages": [],
    },
    "local_automation": {
        "template_id": "local_automation",
        "display_name": "Local Automation",
        "description": "Automate local workflows — file organization, batch processing, cron jobs",
        "mainline_series": ["scan", "classify", "automate", "schedule"],
        "stages": [
            {
                "stage_id": "automation_scan",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": ["goal_contract.yml", "mainline_program.yml"],
                "required_evidence": ["scenario_validation_plan.yml"],
                "acceptance_gates": ["workflow_mapped", "scenario_validated"],
            },
            {
                "stage_id": "automation_deploy",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": ["mainline_progress.yml"],
                "required_evidence": ["automation_script"],
                "acceptance_gates": ["script_tested", "schedule_configured"],
            },
        ],
        "scenario_validations": ["local_automation"],
        "future_reserved_stages": [],
    },
    "unknown_large_project": {
        "template_id": "unknown_large_project",
        "display_name": "Unknown Large Project",
        "description": "Catch-all for projects that don't match a known template — requires explicit planning",
        "mainline_series": ["discovery", "classification", "planning", "execution"],
        "stages": [
            {
                "stage_id": "unknown_discovery",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": ["goal_contract.yml", "mainline_program.yml"],
                "required_evidence": ["scenario_validation_plan.yml"],
                "acceptance_gates": ["domain_classified", "template_matched"],
            },
            {
                "stage_id": "unknown_plan",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": [
                    "mission_contract.yml",
                    "workflow_plan.yml",
                ],
                "required_evidence": ["mainline_program.yml"],
                "acceptance_gates": ["plan_complete"],
            },
        ],
        "scenario_validations": ["unknown_large_project"],
        "future_reserved_stages": [],
    },
}

# Required template IDs that MUST exist for M2 closure
REQUIRED_TEMPLATE_IDS = [
    "agentlab_self_repair",
    "operator_os_goal_management",
    "codebase_build",
    "longform_creation",
    "research_archive",
    "video_generation",
    "document_knowledgebase",
    "local_automation",
    "unknown_large_project",
]


def get_template(template_id: str) -> dict[str, Any] | None:
    """Get a goal template by ID. Returns None if not found."""
    return TEMPLATES.get(template_id)
