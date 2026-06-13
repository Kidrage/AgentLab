from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import re

import yaml

from agent_runtime.external_agents.registry import (
    ExternalAgent,
    get_external_agent,
)


DEFAULT_CONFIG_PATH = Path("config/external_agents.yml")

DEFAULT_CONSTRAINTS = [
    "Do not auto-run external tools from AgentLab.",
    "Do not full clone remote repositories unless explicitly approved.",
    "Do not install dependencies without approval.",
    "Do not copy third-party source code.",
    "Do not expose secrets, API keys, OAuth tokens, or subscription credentials.",
    "Return changed files, commands run, evidence artifacts, and residual risks.",
]

DEFAULT_REQUIRED_OUTPUTS = [
    "implementation_summary",
    "changed_files",
    "tests_run",
    "evidence_artifacts",
    "residual_risks",
    "cost_notes",
]

DEFAULT_EVIDENCE_REQUIREMENTS = {
    "require_changed_files": True,
    "require_test_summary": True,
    "require_execution_log_or_external_unverified_marker": True,
    "require_no_secret_leak": True,
    "require_residual_risks": True,
}


SECRET_PATTERNS = [
    re.compile(r"sk_[A-Za-z0-9_-]{6,}"),
    re.compile(r"(?i)\b(GITHUB_TOKEN|ANYSEARCH_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY)\b\s*[:=]\s*\S+"),
]


def _redact_sensitive_text(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


@dataclass
class _ExternalHandoffData:
    """Internal dataclass for handoff data — not exported."""
    handoff_id: str
    task_id: str
    project: str
    created_at: str
    target: dict[str, Any]
    objective: dict[str, str]
    constraints: list[str]
    required_outputs: list[str]
    budget: dict[str, Any]
    evidence_requirements: dict[str, Any]
    skill_context: dict[str, Any] = field(default_factory=dict)


def create_handoff_id(task_id: str, agent_id: str) -> str:
    """Generate a unique handoff identifier."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    return f"handoff_{task_id}_{agent_id}_{ts}_{short_uuid}"


def build_external_handoff(
    task_id: str,
    project: str,
    agent: ExternalAgent,
    title: str,
    summary: str,
    suggested_external_skills: Optional[list[str]] = None,
) -> _ExternalHandoffData:
    """Build a handoff data object — data only, no execution."""
    handoff_id = create_handoff_id(task_id, agent.agent_id)
    created_at = datetime.now(timezone.utc).isoformat()

    target_status = "proposed" if not agent.enabled else "proposed"

    target = {
        "agent_id": agent.agent_id,
        "display_name": agent.display_name,
        "type": agent.type,
        "integration_mode": agent.integration_mode,
        "enabled": agent.enabled,
        "status": target_status,
    }

    objective = {
        "title": _redact_sensitive_text(title),
        "summary": _redact_sensitive_text(summary),
    }

    billing_mode = agent.billing.get("mode", "unknown")
    api_cost_visible = agent.billing.get("api_cost_visible", False)

    budget: dict[str, Any] = {
        "billing_mode": billing_mode,
        "api_cost_visible": api_cost_visible,
        "external_token_visibility": "unknown",
        "expected_agentlab_api_cost_usd": None,
    }

    skill_context: dict[str, Any] = {}
    if suggested_external_skills:
        skill_context["suggested_external_skills"] = list(suggested_external_skills)

    return _ExternalHandoffData(
        handoff_id=handoff_id,
        task_id=task_id,
        project=project,
        created_at=created_at,
        target=target,
        objective=objective,
        constraints=list(DEFAULT_CONSTRAINTS),
        required_outputs=list(DEFAULT_REQUIRED_OUTPUTS),
        budget=budget,
        evidence_requirements=dict(DEFAULT_EVIDENCE_REQUIREMENTS),
        skill_context=skill_context,
    )


def render_handoff_markdown(handoff: _ExternalHandoffData) -> str:
    """Render a human-readable markdown string for an ExternalHandoff."""
    lines: list[str] = []

    lines.append("# External Agent Handoff")
    lines.append("")
    lines.append(f"**Task ID:** {handoff.task_id}")
    lines.append(f"**Handoff ID:** {handoff.handoff_id}")
    lines.append(f"**Project:** {handoff.project}")
    lines.append(f"**Created At:** {handoff.created_at}")
    lines.append("")

    target = handoff.target
    lines.append("## Target Executor")
    lines.append(f"- **Agent ID:** {target.get('agent_id', 'unknown')}")
    lines.append(f"- **Display Name:** {target.get('display_name', 'unknown')}")
    lines.append(f"- **Type:** {target.get('type', 'unknown')}")
    lines.append(f"- **Integration Mode:** {target.get('integration_mode', 'unknown')}")
    lines.append(f"- **Enabled:** {target.get('enabled', False)}")
    lines.append(f"- **Status:** {target.get('status', 'proposed')}")
    lines.append("")

    obj = handoff.objective
    lines.append("## Objective")
    lines.append(f"**Title:** {obj.get('title', '')}")
    lines.append(f"**Summary:** {obj.get('summary', '')}")
    lines.append("")

    lines.append("## Task Summary")
    lines.append(obj.get("summary", ""))
    lines.append("")

    lines.append("## Repository Context")
    lines.append("- Local checkout context only; do not clone remote repositories.")
    lines.append("- Allowed files and forbidden files must be confirmed before editing.")
    lines.append("")

    lines.append("## Acceptance Criteria")
    lines.append("- Provide implementation or review evidence without exposing secrets.")
    lines.append("- Do not execute external tools automatically from AgentLab.")
    lines.append("- Do not misuse external subscriptions, API keys, or private credentials.")
    lines.append("")

    lines.append("## Constraints")
    for c in handoff.constraints:
        lines.append(f"- {c}")
    lines.append("")

    lines.append("## Required Outputs")
    for ro in handoff.required_outputs:
        lines.append(f"- {ro}")
    lines.append("")

    lines.append("## Evidence Requirements")
    for key, val in handoff.evidence_requirements.items():
        lines.append(f"- **{key}:** {val}")
    lines.append("")

    lines.append("## Budget")
    budget = handoff.budget
    lines.append(f"- **Billing Mode:** {budget.get('billing_mode', 'unknown')}")
    lines.append(f"- **API Cost Visible:** {budget.get('api_cost_visible', False)}")
    lines.append(f"- **Token Visibility:** {budget.get('external_token_visibility', 'unknown')}")
    lines.append(f"- **Expected Agentlab API Cost (USD):** {budget.get('expected_agentlab_api_cost_usd', None)}")
    lines.append("")

    if handoff.skill_context:
        lines.append("## Skill Context")
        skills = handoff.skill_context.get("suggested_external_skills", [])
        if skills:
            for s in skills:
                lines.append(f"- {s}")
        lines.append("")

    lines.append("## How to submit result back to AgentLab")
    lines.append("")
    lines.append("1. Complete the assigned task following all constraints.")
    lines.append("2. Record all changed files, commands run, and artifacts produced.")
    lines.append("3. Prepare a result YAML file with the required outputs listed above.")
    lines.append("4. Run the following command to submit your result:")
    lines.append("")
    lines.append("```bash")
    lines.append(
        f"./agentlab.sh external-agents submit-result "
        f"--task-id {handoff.task_id} "
        f"--handoff-id {handoff.handoff_id} "
        f"--result-file path/to/result.yml"
    )
    lines.append("```")
    lines.append("")
    lines.append("**Note:** AgentLab does NOT automatically execute external agents.")
    lines.append("You must manually perform the work and submit results.")
    lines.append("")

    return "\n".join(lines)


def write_external_handoff(
    handoff: _ExternalHandoffData,
    run_dir: Path,
) -> tuple[Path, Path]:
    """Write handoff YAML and Markdown artifacts to run_dir.
    Returns (yaml_path, md_path). Does NOT execute external agents.
    """
    run_dir.mkdir(parents=True, exist_ok=True)

    yaml_path = run_dir / "external_handoff.yml"
    md_path = run_dir / "external_handoff.md"

    data = asdict(handoff)
    with open(yaml_path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)

    md_content = render_handoff_markdown(handoff)
    with open(md_path, "w") as f:
        f.write(md_content)

    return yaml_path, md_path


# ============================================================
# ExternalHandoff — the public class used by CLI and tests
# ============================================================
class ExternalHandoff:
    """Manages creation and validation of external handoff artifacts."""

    def __init__(self, task_id: str, output_dir: Optional[str] = None):
        self.task_id = task_id
        self.output_dir = output_dir or f"projects/AgentLab/runs/{task_id}"

    def create_handoff(
        self,
        agent_id: str,
        title: str,
        summary: str,
        suggested_external_skills: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Create a handoff — returns dict for backward compat."""
        agent = get_external_agent(DEFAULT_CONFIG_PATH, agent_id)
        project = "AgentLab"

        handoff = build_external_handoff(
            task_id=self.task_id,
            project=project,
            agent=agent,
            title=title,
            summary=summary,
            suggested_external_skills=suggested_external_skills,
        )

        run_dir = Path(self.output_dir)
        write_external_handoff(handoff, run_dir)

        # Write ledger entry
        try:
            from agent_runtime.external_agents.ledger import record_handoff_created

            record_handoff_created(
                ledger_path=run_dir / "external_agent_ledger.yml",
                task_id=self.task_id,
                handoff_id=handoff.handoff_id,
                agent_id=agent.agent_id,
                billing_mode=handoff.budget.get("billing_mode", "unknown"),
                token_visibility=handoff.budget.get("external_token_visibility", "unknown"),
                api_cost_visible=handoff.budget.get("api_cost_visible", False),
                skill_usage_events=(
                    handoff.skill_context.get("suggested_external_skills")
                    if handoff.skill_context
                    else None
                ),
            )
        except ImportError:
            pass

        return asdict(handoff)
