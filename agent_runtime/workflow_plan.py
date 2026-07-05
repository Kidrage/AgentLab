"""Build transparent AgentLab workflow plans without executing agents."""

import copy
import os
import re
from pathlib import Path

from budget_planner import build_token_budgets, normalize_budget_mode, select_budget_profile_key
from config_loader import load_agentlab_configs, load_project_config
from model_resolver import resolve_profile_config
from policies import assert_path_allowed
from routing.route_catalog import RouteCatalog, route_size_suffix
from schemas import AgentRoute, WorkflowPlan
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


def _route_from_mission_contract(mission: dict, routing_config: dict | None) -> AgentRoute | None:
    route_decision = mission.get("route_decision", {}) if isinstance(mission, dict) else {}
    if not isinstance(route_decision, dict):
        return None
    if route_decision.get("action") not in {"select_existing_route", "use_existing_route"}:
        return None
    route_key = route_decision.get("selected_route")
    if not route_key:
        return None
    catalog = RouteCatalog.from_config(routing_config)
    if not catalog.has_route(str(route_key)):
        return None
    return AgentRoute(
        task_size=catalog.size_for(str(route_key)),
        agents=catalog.agents_for(str(route_key)),
        route_key=str(route_key),
        rationale=[
            "Mission contract selected an existing route before legacy task routing.",
            f"Route selected by mission_contract route_decision: {route_key}.",
        ],
    )


def _skill_injection_agents_for_route(route: AgentRoute) -> list[str] | None:
    creative_agents = [agent for agent in ("Writer", "Reviewer", "Scribe") if agent in route.agents]
    return creative_agents or None


def _light_chapter_gates() -> list[dict]:
    return [
        {
            "id": "fiction_draft",
            "owner": "Writer",
            "required": True,
            "description": "Draft the candidate chapter from chapter packet, fact snapshot, artifact index, and prior continuity ledger.",
            "evidence": ["fiction_draft.md"],
        },
        {
            "id": "continuity_ledger",
            "owner": "Writer",
            "required": True,
            "description": "Record plot, character, relationship/worldline, foreshadowing, and timeline updates for the chapter candidate.",
            "evidence": ["continuity_ledger.yml"],
        },
        {
            "id": "state_transition_proposal",
            "owner": "Writer",
            "required": True,
            "description": "Propose candidate fact events and state transitions; do not directly promote facts to production.",
            "evidence": ["state_transition_proposal.yml"],
        },
        {
            "id": "narrative_delivery_receipt",
            "owner": "Writer",
            "required": True,
            "description": "Self-report local deterministic checks and candidate-only delivery status.",
            "evidence": ["narrative_delivery_receipt.yml"],
        },
    ]


def _article_light_gates() -> list[dict]:
    return [
        {
            "id": "article_draft",
            "owner": "ArtifactProducer",
            "required": True,
            "description": "Draft the requested article or explanatory text.",
            "evidence": ["article_draft.md"],
        },
        {
            "id": "article_structure_check",
            "owner": "ArtifactProducer",
            "required": True,
            "description": "Run a simple local structure check for title, sections, audience fit, and unresolved placeholders.",
            "evidence": ["article_structure_check.yml"],
        },
    ]


def _narrative_heavy_audit_gates() -> list[dict]:
    return [
        {
            "id": "fiction_review",
            "owner": "Reviewer",
            "required": True,
            "description": "Audit existing narrative drafts and ledgers for continuity, character state, POV, timeline, and style drift.",
            "evidence": ["fiction_review.yml"],
        },
        {
            "id": "continuity_failure_report",
            "owner": "Reviewer",
            "required": True,
            "description": "Report blocking and non-blocking continuity failures without directly rewriting draft prose.",
            "evidence": ["continuity_failure_report.yml"],
        },
        {
            "id": "state_transition_proposal",
            "owner": "Scribe",
            "required": True,
            "description": "Propose structured fact-state changes needed after audit.",
            "evidence": ["state_transition_proposal.yml"],
        },
        {
            "id": "revision_or_rewrite_proposal",
            "owner": "Verifier",
            "required": True,
            "description": "Emit a rewrite proposal only when blocking issues require it; do not directly alter the draft.",
            "evidence": ["revision_or_rewrite_proposal.yml"],
        },
    ]


def _validation_gates_for_route(configs: dict, route: AgentRoute) -> list[dict]:
    validation_gates = []
    for gate in configs.get("validation_gates", {}).get("gates", []):
        route_keys = gate.get("required_for_routes")
        if not route_keys or route.route_key in route_keys:
            validation_gates.append(gate)

    if route.route_key == "narrative_light_chapter":
        return _light_chapter_gates()

    if route.route_key == "article_light_draft":
        return _article_light_gates()

    if route.route_key == "narrative_heavy_audit":
        return _narrative_heavy_audit_gates()

    if route.route_key != "fiction_chapter_pipeline":
        return validation_gates

    route_agents = set(route.agents)
    shared_gates = [
        gate
        for gate in validation_gates
        if gate.get("owner") in route_agents
        and gate.get("id") not in {"implementation_report", "validation_evidence", "feedback_promotion"}
    ]
    return shared_gates + [
        {
            "id": "fiction_draft",
            "owner": "Writer",
            "required": True,
            "description": "Draft the requested chapter or prose artifact from the approved longform brief.",
            "evidence": ["fiction_draft.md"],
        },
        {
            "id": "fiction_review",
            "owner": "Reviewer",
            "required": True,
            "description": "Review the draft for continuity, POV, character state, timeline, and style drift.",
            "evidence": ["fiction_review.yml"],
        },
        {
            "id": "continuity_update",
            "owner": "Scribe",
            "required": True,
            "description": "Record continuity, character, timeline, relationship, and foreshadowing updates.",
            "evidence": ["continuity_ledger.yml"],
        },
        {
            "id": "final_verification",
            "owner": "Verifier",
            "required": True,
            "description": "Verify requested writing outputs and long-project governance gates.",
            "evidence": ["verification_report.md"],
        },
    ]


def _included_agents_for_route(agent_registry: dict, route: AgentRoute) -> dict[str, dict]:
    included = {
        name: copy.deepcopy(agent_registry.get(name, {}))
        for name in route.agents
    }

    if route.route_key == "narrative_light_chapter" and "Writer" in included:
        included["Writer"]["required_inputs"] = [
            "runs/task_xxxx/mission_contract.yml",
            "runs/task_xxxx/user_request.md",
            "runs/task_xxxx/chapter_packet.yml",
            "project_brain/project_fact_snapshot.yml",
            "project_artifact_index.yml",
            "previous continuity_ledger.yml when available",
        ]
        included["Writer"]["required_outputs"] = [
            "runs/task_xxxx/fiction_draft.md",
            "runs/task_xxxx/continuity_ledger.yml",
            "runs/task_xxxx/state_transition_proposal.yml",
            "runs/task_xxxx/narrative_delivery_receipt.yml",
        ]
        return included

    if route.route_key == "article_light_draft" and "ArtifactProducer" in included:
        included["ArtifactProducer"]["required_inputs"] = [
            "runs/task_xxxx/mission_contract.yml",
            "runs/task_xxxx/user_request.md",
        ]
        included["ArtifactProducer"]["required_outputs"] = [
            "runs/task_xxxx/article_draft.md",
            "runs/task_xxxx/article_structure_check.yml",
        ]
        return included

    if route.route_key == "narrative_heavy_audit":
        if "Reviewer" in included:
            included["Reviewer"]["required_inputs"] = [
                "runs/task_xxxx/fiction_draft.md",
                "runs/task_xxxx/continuity_ledger.yml",
                "runs/task_xxxx/state_transition_proposal.yml",
                "project_brain/project_fact_snapshot.yml",
                "project_artifact_index.yml",
            ]
            included["Reviewer"]["required_outputs"] = [
                "runs/task_xxxx/fiction_review.yml",
                "runs/task_xxxx/continuity_failure_report.yml",
            ]
        if "Scribe" in included:
            included["Scribe"]["required_inputs"] = [
                "runs/task_xxxx/fiction_review.yml",
                "runs/task_xxxx/continuity_failure_report.yml",
            ]
            included["Scribe"]["required_outputs"] = ["runs/task_xxxx/state_transition_proposal.yml"]
        if "Verifier" in included:
            included["Verifier"]["required_inputs"] = [
                "runs/task_xxxx/fiction_review.yml",
                "runs/task_xxxx/continuity_failure_report.yml",
                "runs/task_xxxx/state_transition_proposal.yml",
            ]
            included["Verifier"]["required_outputs"] = ["runs/task_xxxx/revision_or_rewrite_proposal.yml"]
        return included

    if route.route_key != "fiction_chapter_pipeline":
        return included

    if "Verifier" in included:
        included["Verifier"]["required_inputs"] = [
            "runs/task_xxxx/supervisor_plan.md",
            "runs/task_xxxx/mission_contract.yml",
            "runs/task_xxxx/fiction_draft.md",
            "runs/task_xxxx/fiction_review.yml",
            "runs/task_xxxx/continuity_ledger.yml",
        ]
        included["Verifier"]["required_outputs"] = ["runs/task_xxxx/verification_report.md"]

    if "Archivist" in included:
        included["Archivist"]["required_inputs"] = [
            "runs/task_xxxx/supervisor_plan.md",
            "runs/task_xxxx/fiction_draft.md",
            "runs/task_xxxx/fiction_review.yml",
            "runs/task_xxxx/continuity_ledger.yml",
            "runs/task_xxxx/verification_report.md",
            "project_config.yml (bulk mode)",
        ]
        included["Archivist"]["required_outputs"] = ["runs/task_xxxx/archive_update.md"]

    return included


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

    mission = {}
    long_project_governance = {}
    try:
        from agent_runtime.brain.mission_contract import build_mission_contract
        from agent_runtime.long_project_governance import build_project_governance_pack

        mission = build_mission_contract(task_text, project_id=project_name, task_id=task_id, agentlab_root=agentlab_root)
        project_type = mission.get("project_type", "unknown_project")
        if mission.get("is_long_project"):
            long_project_governance = build_project_governance_pack(agentlab_root, project_type, paths["project_root"])
    except Exception as exc:
        long_project_governance = {"enabled": False, "error": f"{type(exc).__name__}: {exc}"}

    route = _route_from_mission_contract(mission, configs.get("routing_rules", {})) or recommend_route(
        task_text,
        routing_config=configs.get("routing_rules", {}),
        known_agents=known_agents,
    )
    resolved_budget_mode = _resolve_budget_mode(configs, task_text, budget_mode)
    risk_level = _classify_risk(task_text, configs.get("routing_policy", {}))
    if risk_level == "R3" and resolved_budget_mode != "max_quality":
        resolved_budget_mode = "max_quality"
    elif risk_level == "R2" and resolved_budget_mode == "frugal":
        resolved_budget_mode = "balanced"
    token_budgets = build_token_budgets(route, configs.get("budget_profiles", {}), resolved_budget_mode)
    budget_profile = select_budget_profile_key(route, configs.get("budget_profiles", {}), resolved_budget_mode)
    route_size = route_size_suffix(route.task_size)
    included_agents = _included_agents_for_route(agent_registry, route)
    model_profiles = {
        name: resolve_profile_config(
            _profile_for_agent(config, route_size, resolved_budget_mode),
            model_profiles=configs.get("model_profiles", {}),
            model_catalog=configs.get("model_catalog", {}),
            agent_name=name,
        )
        for name, config in included_agents.items()
    }

    validation_gates = _validation_gates_for_route(configs, route)

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

    if mission.get("is_long_project"):
        notes.append(f"Long-project governance enabled for {mission.get('project_type', 'unknown_project')}.")

    try:
        from skill_injector import build_skill_plan
        skills = build_skill_plan(
            agentlab_root,
            project=project_name,
            task_id=task_id,
            run_dir=paths["run_dir"],
            task_text=task_text,
            injected_agents=_skill_injection_agents_for_route(route),
            record_usage=False,
        )
    except Exception as exc:
        skills = {
            "selected": [],
            "rejected": [],
            "error": f"skill retrieval unavailable: {type(exc).__name__}: {exc}",
        }

    try:
        from project_artifact_steward import build_artifact_intent
        artifact_intent = build_artifact_intent(agentlab_root, project_name, task_id, project_config)
    except Exception as exc:
        artifact_intent = {"enabled": False, "error": f"{type(exc).__name__}: {exc}"}

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
        included_agents=included_agents,
        model_profiles=model_profiles,
        validation_gates=validation_gates,
        skills=skills,
        memory_policy=configs.get("memory_policy", {}),
        execution_policy=execution_policy,
        harness_policy=configs.get("harness_policy", {}),
        long_project_governance=long_project_governance,
        artifact_intent=artifact_intent,
        missing_inputs=sorted(set(missing_inputs)),
        aider_plan=aider_plan,
        notes=notes,
    )
