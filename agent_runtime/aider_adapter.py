"""Aider adapter planning helpers for AgentLab Phase 2A.

The adapter builds a command plan only. It never installs Aider, starts Aider, or
edits repository files by itself.
"""

from pathlib import Path

from policies import assert_path_allowed
from schemas import AiderInvocationPlan


DEFAULT_READ_CONTEXT = (
    "project_config.yml",
    "agent_docs/00_CONTEXT_PACK.md",
    "agent_docs/01_REPO_MAP.md",
)


def build_aider_plan(
    agentlab_root: Path,
    project_name: str,
    task_id: str,
    editable_files: list[str] | None = None,
) -> AiderInvocationPlan:
    """Create a safe Aider command plan for the Coder phase."""
    project_root = assert_path_allowed(agentlab_root / "projects" / project_name, agentlab_root)
    repo_path = assert_path_allowed(project_root / "repo", agentlab_root)
    run_dir = assert_path_allowed(project_root / "runs" / task_id, agentlab_root)
    user_request = assert_path_allowed(run_dir / "user_request.md", agentlab_root)

    context_paths = [project_root / rel for rel in DEFAULT_READ_CONTEXT]
    context_paths.extend(
        [
            agentlab_root / "agent_templates" / "coder.md",
            run_dir / "supervisor_plan.md",
            run_dir / "reposcout_report.md",
        ]
    )
    safe_context_paths = [assert_path_allowed(path, agentlab_root) for path in context_paths]
    read_context = [str(path) for path in safe_context_paths]
    missing_inputs = [
        str(path)
        for path in [repo_path, user_request, *safe_context_paths]
        if not path.exists()
    ]

    if missing_inputs:
        return AiderInvocationPlan(
            enabled=False,
            repo_path=str(repo_path),
            read_only_context=read_context,
            editable_files=editable_files or [],
            message_file=str(user_request),
            missing_inputs=missing_inputs,
            notes=[
                "Plan disabled: required AgentLab context files are missing.",
                "Create the missing project docs/run reports before using Aider as Coder backend.",
            ],
        )

    editable = editable_files or []
    command = ["aider"]
    for context_file in read_context:
        command.extend(["--read", context_file])
    command.extend(["--message-file", str(user_request)])
    command.extend(editable)

    return AiderInvocationPlan(
        enabled=True,
        repo_path=str(repo_path),
        command=command,
        read_only_context=read_context,
        editable_files=editable,
        message_file=str(user_request),
        missing_inputs=[],
        notes=[
            "Plan only: AgentLab does not run this command in Phase 2A.",
            "Editable files should be limited by the Supervisor plan.",
            "Run Aider from repo_path so its git safeguards apply to the target repository.",
        ],
    )
