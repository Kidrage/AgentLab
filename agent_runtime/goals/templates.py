from typing import Dict, Any

TEMPLATES = {
    "agentlab_self_repair": {
        "template_id": "agentlab_self_repair",
        "display_name": "AgentLab Self Repair",
        "description": "Repair and evolve the AgentLab codebase",
        "mainline_series": ["project_governance_kernel", "operator_os", "p2r_os_future"],
        "stages": [
            {
                "stage_id": "m1_kernel",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": ["goal_contract.yml"],
                "required_evidence": [],
                "acceptance_gates": []
            },
            {
                "stage_id": "m2_operator",
                "status": "pending",
                "blocks_m2_closure": True,
                "required_artifacts": ["mainline_program.yml"],
                "required_evidence": ["operator_demo_report"],
                "acceptance_gates": ["demo_passed"]
            },
            {
                "stage_id": "m3_revenue",
                "status": "future_reserved",
                "blocks_m2_closure": False,
                "required_artifacts": [],
                "required_evidence": [],
                "acceptance_gates": []
            }
        ],
        "scenario_validations": ["agentlab_self_repair"],
        "future_reserved_stages": ["m3_revenue"]
    },
    "longform_creation": {
        "template_id": "longform_creation",
        "display_name": "Longform Creation",
        "description": "Create longform novels or stories",
        "mainline_series": ["planning", "drafting", "editing"],
        "stages": [],
        "scenario_validations": ["longform_creation"],
        "future_reserved_stages": []
    },
    "codebase_build": {
        "template_id": "codebase_build",
        "display_name": "Codebase Build",
        "description": "Build a new codebase or app",
        "mainline_series": ["architecture", "implementation", "testing"],
        "stages": [],
        "scenario_validations": ["codebase_build"],
        "future_reserved_stages": []
    },
    "research_archive": {
        "template_id": "research_archive",
        "display_name": "Research Archive",
        "description": "Research and archive knowledge",
        "mainline_series": ["collection", "analysis", "archiving"],
        "stages": [],
        "scenario_validations": ["research_archive"],
        "future_reserved_stages": []
    },
    "video_generation": {
        "template_id": "video_generation",
        "display_name": "Video Generation",
        "description": "Generate video content",
        "mainline_series": ["scripting", "generation", "editing"],
        "stages": [],
        "scenario_validations": ["video_generation"],
        "future_reserved_stages": []
    },
    "document_knowledgebase": {
        "template_id": "document_knowledgebase",
        "display_name": "Document Knowledgebase",
        "description": "Build a document knowledgebase",
        "mainline_series": ["ingestion", "indexing", "retrieval"],
        "stages": [],
        "scenario_validations": ["document_knowledgebase"],
        "future_reserved_stages": []
    },
    "local_automation": {
        "template_id": "local_automation",
        "display_name": "Local Automation",
        "description": "Automate local tasks",
        "mainline_series": ["scripting", "testing", "deployment"],
        "stages": [],
        "scenario_validations": ["local_automation"],
        "future_reserved_stages": []
    },
    "unknown_large_project": {
        "template_id": "unknown_large_project",
        "display_name": "Unknown Large Project",
        "description": "A generic large project",
        "mainline_series": ["planning", "execution", "delivery"],
        "stages": [],
        "scenario_validations": ["unknown_large_project"],
        "future_reserved_stages": []
    }
}

def select_template(text: str) -> Dict[str, Any]:
    text_lower = text.lower()
    
    if any(kw in text_lower for kw in ["agentlab", "self repair", "mainline repair", "m-series"]):
        return TEMPLATES["agentlab_self_repair"]
    
    if any(kw in text_lower for kw in ["novel", "longform", "story", "writing"]):
        return TEMPLATES["longform_creation"]
        
    if any(kw in text_lower for kw in ["codebase", "repo", "software", "app"]):
        return TEMPLATES["codebase_build"]
        
    if any(kw in text_lower for kw in ["research", "paper", "archive", "knowledge"]):
        return TEMPLATES["research_archive"]
        
    if any(kw in text_lower for kw in ["video", "short drama", "generation"]):
        return TEMPLATES["video_generation"]
        
    if any(kw in text_lower for kw in ["automation", "local task"]):
        return TEMPLATES["local_automation"]
        
    return TEMPLATES["unknown_large_project"]
