import yaml
from pathlib import Path
from agent_runtime.project_workflows.models import ProjectWorkflowPlan

def render_markdown(plan: ProjectWorkflowPlan) -> str:
    lines = []
    lines.append(f"# Project Workflow Plan: {plan.project_id or 'Unnamed Project'}")
    lines.append(f"")
    lines.append(f"- **Template ID**: `{plan.template_id}`")
    lines.append(f"- **Project Type**: `{plan.project_type}`")
    lines.append(f"- **Mission Contract**: `{plan.mission_contract_path}`")
    lines.append(f"")
    
    if plan.warnings:
        lines.append(f"## ⚠️ Warnings")
        for w in plan.warnings:
            lines.append(f"- {w}")
        lines.append(f"")
        
    if plan.decision_points:
        lines.append(f"## 📋 Decision Points / Cards")
        for dp in plan.decision_points:
            lines.append(f"- `{dp}`")
        lines.append(f"")
        
    lines.append(f"## Phases")
    lines.append(f"")
    for phase in plan.phases:
        lines.append(f"### {phase.phase_id.upper()}: {phase.title.replace('_', ' ').title()}")
        lines.append(f"- **Goal**: {phase.goal}")
        if phase.recommended_executors:
            lines.append(f"- **Recommended Executors**: {', '.join(phase.recommended_executors)}")
        if phase.expected_artifacts:
            lines.append(f"- **Expected Artifacts**: {', '.join(phase.expected_artifacts)}")
        if phase.artifact_intent:
            lines.append(f"- **Candidate Directory**: `{phase.artifact_intent.get('candidate_dir', '')}`")
            lines.append(f"- **Production Directory**: `{phase.artifact_intent.get('production_dir', '')}`")
        if phase.acceptance_gates:
            lines.append(f"- **Acceptance Gates**: {', '.join(phase.acceptance_gates)}")
        lines.append(f"")
    return "\n".join(lines)

def write_workflow_plan(plan: ProjectWorkflowPlan, out_dir: Path) -> None:
    """Write project_workflow_plan.yml and project_workflow_plan.md to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Save YAML
    if hasattr(plan, "model_dump"):
        plan_dict = plan.model_dump()
    else:
        plan_dict = plan.dict()
        
    yaml_path = out_dir / "project_workflow_plan.yml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(plan_dict, f, default_flow_style=False, sort_keys=False)
        
    # Save Markdown
    md_path = out_dir / "project_workflow_plan.md"
    md_content = render_markdown(plan)
    md_path.write_text(md_content, encoding="utf-8")
