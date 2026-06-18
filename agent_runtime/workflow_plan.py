"""Build transparent AgentLab workflow plans without executing agents."""

import os
import re
from pathlib import Path

from budget_planner import build_token_budgets, normalize_budget_mode, select_budget_profile_key
from config_loader import load_agentlab_configs, load_project_config
from model_resolver import resolve_profile_config
from policies import assert_path_allowed
from schemas import WorkflowPlan
from task_router import recommend_route


def _resolve_configured_path(
    project_root: Path,
    configured: str | None,
    default: str,
    agentlab_root: Path,
    *,
    extra_roots: list[Path] | None = None,
) -> Path:
    """Resolve a project-configured path relative to the project root.

    AgentLab projects may bind their source repo to a sibling path such as
    `../../`.  Resolve from `project_root`, then keep the final path inside the
    AgentLab workspace boundary.
    """
    raw = configured or default
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return assert_path_allowed(candidate, agentlab_root, extra_roots=extra_roots)


def _project_docs_path(project_root: Path, configured: str | None, agentlab_root: Path) -> Path:
    raw = configured or "agent_docs"
    docs = Path(raw).expanduser()
    if not docs.is_absolute():
        docs = project_root / docs
    if docs.is_symlink() and not docs.exists():
        local_backup = docs.with_name(f"{docs.name}.local.bak")
        if local_backup.is_dir():
            return assert_path_allowed(local_backup, agentlab_root)
    return assert_path_allowed(docs, agentlab_root)


def _project_paths(agentlab_root: Path, project_name: str, task_id: str, project_config: dict | None = None) -> dict[str, Path]:
    project_root = assert_path_allowed(agentlab_root / "projects" / project_name, agentlab_root)
    paths_config = (project_config or {}).get("paths", {})
    external_readonly_roots = [
        Path(root)
        for root in (project_config or {}).get("scope", {}).get("external_readonly_roots", [])
    ]
    repo_path = _resolve_configured_path(
        project_root,
        paths_config.get("repo"),
        "repo",
        agentlab_root,
        extra_roots=external_readonly_roots,
    )
    docs_path = _project_docs_path(project_root, paths_config.get("docs"), agentlab_root)
    run_base = _resolve_configured_path(project_root, paths_config.get("runs"), "runs", agentlab_root)
    run_dir = assert_path_allowed(run_base / task_id, agentlab_root)
    return {
        "project_root": project_root,
        "repo_path": repo_path,
        "run_dir": run_dir,
        "project_config": project_root / "project_config.yml",
        "context_pack": docs_path / "00_CONTEXT_PACK.md",
        "repo_map": docs_path / "01_REPO_MAP.md",
        "user_request": run_dir / "user_request.md",
    }


def _route_size_suffix(task_size: str) -> str:
    return {"small": "L1", "medium": "L2", "large": "L3"}.get(task_size, "L2")


def _profile_for_agent(agent_config: dict, route_size: str, budget_mode: str) -> str:
    """Resolve an agent model profile from profile_mapping before fallback."""
    mappings = agent_config.get("profile_mapping", {}) or {}
    mode_key = normalize_budget_mode(budget_mode)
    legacy_key = "brain_allocated" if mode_key == "balanced" else mode_key
    mode_mapping = mappings.get(mode_key) or mappings.get(legacy_key) or mappings.get("brain_allocated") or {}
    if isinstance(mode_mapping, dict):
        direct = mode_mapping.get(route_size)
        if direct:
            return direct
        any_profile = mode_mapping.get("any")
        if any_profile:
            return any_profile
        # Frugal Coder mappings may distinguish local availability. Runtime does
        # not yet probe local LLM here, so keep the API fallback.
        no_local = mode_mapping.get("no_local")
        if no_local:
            return no_local
    return agent_config.get("model_profile", "")


def _budget_mode_from_request(task_text: str) -> str | None:
    match = re.search(r"(?im)^\s*budget_mode\s*:\s*([\w\-]+)\s*$", task_text or "")
    return match.group(1) if match else None


def _resolve_budget_mode(configs: dict, task_text: str, explicit_budget_mode: str | None = None) -> str:
    default_mode = (
        configs.get("execution_policy", {})
        .get("budget_mode_policy", {})
        .get("default_budget_mode")
        or configs.get("budget_profiles", {}).get("defaults", {}).get("budget_mode")
        or "balanced"
    )
    return normalize_budget_mode(
        explicit_budget_mode
        or os.getenv("AGENTLAB_BUDGET_MODE")
        or _budget_mode_from_request(task_text)
        or default_mode
    )


def _classify_risk(task_text: str, routing_policy: dict) -> str:
    text = (task_text or "").lower()
    risk_keywords = routing_policy.get("risk_keywords", {}) if routing_policy else {}
    critical = [str(x).lower() for x in risk_keywords.get("critical", [])]
    high = [str(x).lower() for x in risk_keywords.get("high", [])]
    if any(k and k in text for k in critical):
        return "R3"
    if any(k and k in text for k in high):
        return "R2"
    return "R1" if text.strip() else "R0"


def _risk_max(*levels: str) -> str:
    rank = {"R0": 0, "R1": 1, "R2": 2, "R3": 3}
    normalized = [level if level in rank else "R1" for level in levels if level]
    if not normalized:
        return "R0"
    return max(normalized, key=lambda level: rank[level])


def _compile_execution_profile(task_text: str, project_name: str, task_id: str) -> tuple[dict, list[str]]:
    if not task_text.strip():
        return {}, ["Brain compiler skipped because user request is empty."]
    try:
        from agent_runtime.brain.task_compiler import TaskCompilationError, compile_task_packet

        result = compile_task_packet(task_text, task_id=task_id, project=project_name)
        notes = [
            f"Brain compiler selected template {result.selected_template_id}.",
            f"Brain execution profile: {result.execution_profile.get('task_size', '?')}/"
            f"{result.execution_profile.get('risk_level', '?')}/"
            f"{result.execution_profile.get('route_key_hint', '?')}.",
        ]
        for warning in result.warnings[:3]:
            notes.append(f"Brain compiler warning: {warning}")
        return result.execution_profile, notes
    except TaskCompilationError as exc:
        return {}, [f"Brain compiler returned structured errors; keyword route fallback used: {exc.errors}"]
    except Exception as exc:
        return {}, [f"Brain compiler unavailable; keyword route fallback used: {type(exc).__name__}: {exc}"]


def _skipped_agent_reason(agent: str, route_key: str, execution_profile: dict) -> str:
    boundaries = set(execution_profile.get("boundaries") or [])
    if agent == "Researcher":
        if "web_research_is_mock_or_source_plan_until_network_approved" in boundaries:
            return "Live research skipped until network policy and allowlist approval exist."
        return "No external/current-source requirement in the selected route."
    if agent == "InterfaceMapper":
        return "No interface, schema, protocol, or integration boundary required for this phase."
    if agent == "RepoScout":
        return "Route is narrow enough for targeted inspection instead of broad repo scouting."
    if agent == "Archivist":
        return "Archival handoff can wait until a broader or completed phase."
    if agent == "Verifier":
        return "Independent verification skipped for lightweight phase; TesterAuditor or targeted checks remain expected."
    if agent == "Coder":
        return "Analysis-only route; implementation is not requested for this phase."
    if route_key == "small_task":
        return "Skipped by small-task route controls."
    return "Skipped by selected route controls."


def _build_route_controls(route, execution_profile: dict, risk_level: str, budget_mode: str) -> dict:
    boundaries = list(execution_profile.get("boundaries") or [])
    failure_policy = str(execution_profile.get("failure_policy") or "keyword_route_boundary")
    approval_first = risk_level == "R3" or any("approval" in boundary for boundary in boundaries)
    mock_first = any("network" in boundary or "mock" in boundary for boundary in boundaries)
    recovery_artifacts = []
    if boundaries:
        recovery_artifacts.extend([
            "recovery/failure_event.json",
            "recovery/failure_diagnosis.json",
            "recovery/recovery_plan.md",
            "recovery/recovery_verdict.json",
        ])
    if approval_first:
        recovery_artifacts.append("recovery/human_review_decision.json")

    skipped_reasons = {
        agent: _skipped_agent_reason(agent, route.route_key, execution_profile)
        for agent in route.skipped_agents
    }

    return {
        "schema_version": 1,
        "source": "brain_execution_profile" if execution_profile else "keyword_router_fallback",
        "route_key": route.route_key,
        "task_size": route.task_size,
        "risk_level": risk_level,
        "budget_mode": budget_mode,
        "failure_policy": failure_policy,
        "mock_first": mock_first,
        "approval_first": approval_first,
        "recovery_boundaries": boundaries,
        "skipped_agent_reasons": skipped_reasons,
        "recovery_artifacts_if_blocked": list(dict.fromkeys(recovery_artifacts)),
    }


def build_workflow_plan(
    agentlab_root: Path,
    project_name: str,
    task_id: str,
    execution_backend: str = "codex",
    user_request_path: Path | None = None,
    budget_mode: str | None = None,
) -> WorkflowPlan:
    """Build a complete, inspectable plan for one AgentLab task."""
    configs = load_agentlab_configs(agentlab_root)
    project_config = load_project_config(agentlab_root, project_name)
    paths = _project_paths(agentlab_root, project_name, task_id, project_config)
    request_path = user_request_path or paths["user_request"]
    task_text = request_path.read_text(encoding="utf-8") if request_path.exists() else ""
    agent_registry = configs.get("agent_registry", {}).get("agents", {})
    known_agents = list(agent_registry.keys()) or None
    execution_profile, brain_notes = _compile_execution_profile(task_text, project_name, task_id)

    route = recommend_route(
        task_text,
        routing_config=configs.get("routing_rules", {}),
        known_agents=known_agents,
        brain_profile=execution_profile,
    )
    profile_budget_mode = execution_profile.get("budget_mode") if execution_profile else None
    budget_hint = budget_mode
    if budget_hint is None and not os.getenv("AGENTLAB_BUDGET_MODE") and not _budget_mode_from_request(task_text):
        budget_hint = profile_budget_mode
    resolved_budget_mode = _resolve_budget_mode(configs, task_text, budget_hint)
    risk_level = _risk_max(
        _classify_risk(task_text, configs.get("routing_policy", {})),
        str(execution_profile.get("risk_level") or "") if execution_profile else "",
    )
    if risk_level == "R3" and resolved_budget_mode != "max_quality":
        resolved_budget_mode = "max_quality"
    elif risk_level == "R2" and resolved_budget_mode == "frugal":
        resolved_budget_mode = "balanced"
    token_budgets = build_token_budgets(route, configs.get("budget_profiles", {}), resolved_budget_mode)
    budget_profile = select_budget_profile_key(route, configs.get("budget_profiles", {}), resolved_budget_mode)
    route_size = _route_size_suffix(route.task_size)
    route_controls = _build_route_controls(route, execution_profile, risk_level, resolved_budget_mode)
    included_agents = {
        name: agent_registry.get(name, {})
        for name in route.agents
    }
    model_profiles = {
        name: resolve_profile_config(
            _profile_for_agent(config, route_size, resolved_budget_mode),
            model_profiles=configs.get("model_profiles", {}),
            model_catalog=configs.get("model_catalog", {}),
            agent_name=name,
        )
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
    notes.extend(brain_notes)
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

    try:
        from skill_injector import build_skill_plan
        skills = build_skill_plan(
            agentlab_root,
            project=project_name,
            task_id=task_id,
            run_dir=paths["run_dir"],
            task_text=task_text,
            record_usage=False,
        )
    except Exception as exc:
        skills = {
            "selected": [],
            "rejected": [],
            "error": f"skill retrieval unavailable: {type(exc).__name__}: {exc}",
        }

    return WorkflowPlan(
        project=project_name,
        task_id=task_id,
        agentlab_root=str(agentlab_root),
        project_root=str(paths["project_root"]),
        repo_path=str(paths["repo_path"]),
        run_dir=str(paths["run_dir"]),
        user_request_path=str(request_path),
        execution_backend=execution_backend,
        budget_mode=resolved_budget_mode,
        budget_profile=budget_profile,
        project_size=route_size,
        risk_level=risk_level,
        route=route,
        token_budgets=token_budgets,
        execution_profile=execution_profile,
        route_controls=route_controls,
        included_agents=included_agents,
        model_profiles=model_profiles,
        validation_gates=validation_gates,
        skills=skills,
        memory_policy=configs.get("memory_policy", {}),
        execution_policy=execution_policy,
        harness_policy=configs.get("harness_policy", {}),
        missing_inputs=sorted(set(missing_inputs)),
        aider_plan=aider_plan,
        notes=notes,
    )
