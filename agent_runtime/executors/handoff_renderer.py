from __future__ import annotations

from pathlib import Path

def render_handoff(task_packet: dict, out_dir: Path) -> Path:
    packet = task_packet.get("task_packet") or task_packet
    executor_type = packet.get("executor_type", "local_cli_generic")
    
    title = f"# External Execution Handoff: {executor_type}"
    
    lines = [
        title,
        "",
        "## Objective",
        packet.get("objective", "No objective provided."),
        "",
        "## Context Summary",
        packet.get("context_summary", "No context summary provided."),
        "",
        "## Allowed Files",
    ]
    for f in packet.get("allowed_files") or []:
        lines.append(f"- {f}")
    lines.append("")
    lines.append("## Forbidden Files")
    for f in packet.get("forbidden_files") or []:
        lines.append(f"- {f}")
    lines.append("")

    lines.append("## Plan Contract")
    lines.append(f"- plan_status: {packet.get('plan_status', 'legacy_ready')}")
    lines.append("- self_check: " + ("passed" if (packet.get("self_check") or {}).get("passed") else "not_passed"))
    lines.append("")
    lines.append("## Must Read Artifacts")
    for ref in packet.get("must_read_artifacts") or []:
        lines.append(f"- {ref}")
    if not packet.get("must_read_artifacts"):
        lines.append("- None listed")
    lines.append("")
    lines.append("## Missing Facts")
    for fact in packet.get("missing_facts") or []:
        if isinstance(fact, dict):
            lines.append(f"- {fact.get('fact')}: {fact.get('reason')}")
        else:
            lines.append(f"- {fact}")
    if not packet.get("missing_facts"):
        lines.append("- None")
    lines.append("")
    lines.append("## Revision Log")
    for item in packet.get("revision_log") or []:
        if isinstance(item, dict):
            lines.append(f"- {item.get('date', 'undated')}: {item.get('change', item)}")
        else:
            lines.append(f"- {item}")
    if not packet.get("revision_log"):
        lines.append("- None")
    lines.append("")
    
    lines.append("## Required Outputs")
    for out in packet.get("required_outputs") or []:
        lines.append(f"- {out}")
    lines.append("")
    
    lines.append("## Acceptance Criteria")
    for criteria in packet.get("acceptance_criteria") or []:
        lines.append(f"- {criteria}")
    lines.append("")
    
    lines.append("## Safety Notes")
    for note in packet.get("safety_notes") or []:
        lines.append(f"- {note}")
    lines.append("")
    
    # Custom executor-specific instructions
    if executor_type in {"claude_code_handoff", "claude_code"}:
        lines.extend([
            "## Claude Code Instructions",
            "- Use the `claude` CLI to execute changes.",
            "- Ensure no forbidden commands (like push) are run.",
        ])
    elif executor_type == "hermes_handoff":
        lines.extend([
            "## Hermes Instructions",
            "- Use hermes agent to execute the requested changes.",
        ])
    elif executor_type in {"codex_handoff", "codex"}:
        lines.extend([
            "## Codex Instructions",
            "- Use Codex tool to apply code changes.",
        ])
    elif executor_type == "manual_patch_submitter":
        lines.extend([
            "## Manual Patch Instructions",
            "- Create standard diffs for manual review.",
        ])
    else:
        lines.extend([
            "## General CLI Instructions",
            "- Execute the task using standard local CLI workflow.",
        ])
        
    lines.append("")
    content = "\n".join(lines)
    
    handoff_file = out_dir / "external_execution_handoff.md"
    out_dir.mkdir(parents=True, exist_ok=True)
    handoff_file.write_text(content, encoding="utf-8")
    return handoff_file
