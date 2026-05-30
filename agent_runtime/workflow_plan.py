"""Build transparent AgentLab workflow plans without executing agents."""

from pathlib import Path

from budget_planner import build_token_budgets
from config_loader import load_agentlab_configs, load_project_config
from policies import assert_path_allowed
from schemas import WorkflowPlan
from task_router import recommend_route


def _project_paths(agentlab_root: Path, project_name: str, task_id: str) -> dict[str, Path]:
    project_root = assert_path_allowed(agentlab_root / "projects" / project_name, agentlab_root)
    repo_path = assert_path_allowed(project_root / "repo", agentlab_root)
    run_dir = assert_path_allowed(project_root / "runs" / task_id, agentlab_root)
    return {
        "project_root": project_root,
        "repo_path": repo_path,
        "run_dir": run_dir,
        "project_config": project_root / "project_config.yml",
        "context_pack": project_root / "agent_docs" / "00_CONTEXT_PACK.md",
        "repo_map": project_root / "agent_docs" / "01_REPO_MAP.md",
        "user_request": run_dir / "user_request.md",
    }


def build_workflow_plan(
    agentlab_root: Path,
    project_name: str,
    task_id: str,
    execution_backend: str = "codex",
    user_request_path: Path | None = None,
) -> WorkflowPlan:
    """Build a complete, inspectable plan for one AgentLab task."""
    paths = _project_paths(agentlab_root, project_name, task_id)
    request_path = user_request_path or paths["user_request"]
    task_text = request_path.read_text(encoding="utf-8") if request_path.exists() else ""

    configs = load_agentlab_configs(agentlab_root)
    project_config = load_project_config(agentlab_root, project_name)
    agent_registry = configs.get("agent_registry", {}).get("agents", {})
    known_agents = list(agent_registry.keys()) or None

    route = recommend_route(
        task_text,
        routing_config=configs.get("routing_rules", {}),
        known_agents=known_agents,
    )
    token_budgets = build_token_budgets(route, configs.get("budget_profiles", {}))
    included_agents = {
        name: agent_registry.get(name, {})
        for name in route.agents
    }
    profiles = configs.get("model_profiles", {}).get("profiles", {})
    model_profiles = {
        name: profiles.get(config.get("model_profile", ""), {})
        for name, config in included_agents.items()
    }

    validation_gates = []
    for gate in configs.get("validation_gates", {}).get("gates", []):
        route_keys = gate.get("required_for_routes")
        if not route_keys or route.route_key in route_keys:
            validation_gates.append(gate)

    missing_inputs = [
        str(path)
        for path in [
            agentlab_root / "AGENTS.md",
            agentlab_root / "config" / "harness_policy.yml",
            paths["project_config"],
            paths["context_pack"],
            paths["repo_map"],
            request_path,
        ]
        if not path.exists()
    ]

    aider_plan = None  # aider backend removed; qwen API is now the Coder fallback

    notes = [
        "Plan only: no model calls, source edits, dependency installs, or validation commands were run.",
        "Use this plan as the visible contract before starting agent execution.",
    ]
    execution_policy = configs.get("execution_policy", {})
    brain_policy = execution_policy.get("brain_policy", {})
    if brain_policy.get("deepseek_required_for_all_agentlab_tasks", False):
        notes.append(
            "Brain policy: DeepSeek must execute planning/review brain stages for simulated, small, and large AgentLab tasks."
        )
        notes.append("Codex may not silently simulate the brain layer unless the user changes the policy.")
    if project_config:
        notes.append("Project config loaded.")
    else:
        notes.append("Project config missing or empty.")

    return WorkflowPlan(
        project=project_name,
        task_id=task_id,
        agentlab_root=str(agentlab_root),
        project_root=str(paths["project_root"]),
        repo_path=str(paths["repo_path"]),
        run_dir=str(paths["run_dir"]),
        user_request_path=str(request_path),
        execution_backend=execution_backend,
        route=route,
        token_budgets=token_budgets,
        included_agents=included_agents,
        model_profiles=model_profiles,
        validation_gates=validation_gates,
        memory_policy=configs.get("memory_policy", {}),
        execution_policy=execution_policy,
        harness_policy=configs.get("harness_policy", {}),
        missing_inputs=sorted(set(missing_inputs)),
        aider_plan=aider_plan,
        notes=notes,
    )
