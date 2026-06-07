"""Brain governance helpers for AgentLab."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

from config_loader import load_agentlab_configs
from schemas import BrainDecision, WorkflowPlan
from state_store import utc_now


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def append_brain_decision(run_dir: Path, decision: BrainDecision) -> Path:
    path = run_dir / "brain_decisions.yml"
    data = load_yaml(path)
    data.setdefault("decisions", [])
    data["decisions"].append(decision.model_dump(mode="json"))
    from atomic_io import atomic_write_text
    atomic_write_text(path, yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def write_user_decision(run_dir: Path, decision: BrainDecision) -> Path:
    path = run_dir / "USER_DECISION_REQUIRED.md"
    text = f"""# User Decision Required

Task: {decision.task_id}
Agent: {decision.agent_name}
Decision type: {decision.decision_type}

## Question
{decision.question}

## Default Recommendation
{decision.default_recommendation}

## Reason
{decision.reason}

## Requested Scope
{decision.requested_scope or "n/a"}

## Approved/Narrowed Scope
{decision.approved_scope or "n/a"}

## Token Impact
- Estimated tokens: {decision.estimated_tokens}
- Current usage: {decision.token_usage_total}
- Budget total: {decision.token_budget_total}

Reply in the main Codex conversation with your decision and any constraint you want applied.
"""
    path.write_text(text, encoding="utf-8")
    return path


def usage_by_agent(run_dir: Path) -> dict[str, int]:
    ledger = load_yaml(run_dir / "cost_ledger.yml")
    usage: dict[str, int] = defaultdict(int)
    for entry in ledger.get("entries", []):
        agent = entry.get("agent") or entry.get("agent_name") or "unknown"
        total = entry.get("total_tokens") or 0
        usage[agent] += int(total)
    return dict(usage)


def budget_by_agent(plan: WorkflowPlan) -> dict[str, int]:
    budgets: dict[str, int] = defaultdict(int)
    for budget in plan.token_budgets:
        phase = budget.phase.lower()
        agent = None
        if "intake" in phase:
            agent = "Supervisor"
        elif "coder" in phase:
            agent = "Coder"
        elif "tester" in phase or "audit" in phase:
            agent = "TesterAuditor"
        elif "repo" in phase:
            agent = "RepoScout"
        elif "research" in phase:
            agent = "Researcher"
        elif "interface" in phase:
            agent = "InterfaceMapper"
        elif "archivist" in phase:
            agent = "Archivist"
        if agent:
            budgets[agent] += budget.estimated_total_tokens
    return dict(budgets)


def evaluate_token_status(plan: WorkflowPlan, agentlab_root: Path) -> dict[str, dict[str, Any]]:
    configs = load_agentlab_configs(agentlab_root)
    token_rules = configs.get("brain_governance", {}).get("token_governance", {})
    warning_ratio = float(token_rules.get("warning_ratio", 0.9))
    stop_ratio = float(token_rules.get("stop_ratio", 1.15))

    run_dir = Path(plan.run_dir)
    usage = usage_by_agent(run_dir)
    budgets = budget_by_agent(plan)
    statuses: dict[str, dict[str, Any]] = {}
    for agent in plan.route.agents:
        budget = budgets.get(agent, 0)
        used = usage.get(agent, 0)
        if budget <= 0:
            state = "unbudgeted"
        elif used >= budget * stop_ratio:
            state = "ask_user"
        elif used >= budget * warning_ratio:
            state = "continue_with_warning"
        else:
            state = "ok"
        statuses[agent] = {
            "budget": budget,
            "used": used,
            "warning_at": int(budget * warning_ratio) if budget else None,
            "stop_at": int(budget * stop_ratio) if budget else None,
            "state": state,
        }
    return statuses


def _age_days(path: Path) -> float | None:
    if not path.exists():
        return None
    return (utc_now_dt().timestamp() - path.stat().st_mtime) / 86400


def utc_now_dt():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _is_placeholder(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    return "TBD" in text or "Placeholder" in text


def _line_count(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def evaluate_harness_status(plan: WorkflowPlan, agentlab_root: Path) -> dict[str, Any]:
    """Check whether the repo-local harness is healthy enough for brain work."""
    configs = load_agentlab_configs(agentlab_root)
    policy = configs.get("harness_policy", {})
    map_rules = policy.get("map_governance", {})
    freshness_rules = policy.get("freshness", {}).get("warn_after_days", {})
    feedback_rules = policy.get("feedback_loop", {})

    project_root = Path(plan.project_root)
    project_docs = project_root / "agent_docs"
    if project_docs.is_symlink() and not project_docs.exists():
        local_backup = project_docs.with_name("agent_docs.local.bak")
        if local_backup.is_dir():
            project_docs = local_backup
    run_dir = Path(plan.run_dir)
    route_agents = set(plan.route.agents)
    checks: list[dict[str, Any]] = []
    recommendations: list[str] = []

    def add_check(scope: str, rel: str, path: Path, missing_state: str = "warn") -> None:
        if path.exists():
            state = "pending" if _is_placeholder(path) else "ok"
            reason = "placeholder" if state == "pending" else "present"
        else:
            state = missing_state
            reason = "missing"
        checks.append({"scope": scope, "path": rel, "state": state, "reason": reason})
        if state in {"warn", "ask_user"}:
            recommendations.append(f"Create or refresh {rel}.")

    for rel in map_rules.get("required_root_maps", []):
        add_check("workspace", rel, agentlab_root / rel)

    root_map = map_rules.get("root_map", "AGENTS.md")
    max_lines = int(map_rules.get("max_root_map_lines", 120))
    root_map_path = agentlab_root / root_map
    if root_map_path.exists():
        lines = _line_count(root_map_path)
        if lines > max_lines:
            checks.append({
                "scope": "workspace",
                "path": root_map,
                "state": "warn",
                "reason": f"map too long: {lines} lines > {max_lines}",
            })
            recommendations.append(f"Shorten {root_map} so it stays a map, not a manual.")

    for rel in map_rules.get("required_project_maps", []):
        if rel.startswith("agent_docs/"):
            add_check("project", rel, project_docs / rel.removeprefix("agent_docs/"))
        else:
            add_check("project", rel, project_root / rel)

    for rel, max_age in freshness_rules.items():
        path = project_docs / rel.removeprefix("agent_docs/") if rel.startswith("agent_docs/") else project_root / rel
        age = _age_days(path)
        if age is not None and age > float(max_age):
            checks.append({
                "scope": "project",
                "path": rel,
                "state": "warn",
                "reason": f"stale: {age:.1f} days > {max_age}",
            })
            recommendations.append(f"Review stale project memory: {rel}.")

    for rel in feedback_rules.get("required_task_artifacts", []):
        if rel in {"06_implementation_report.md", "implementation_report.md"} and "Coder" not in route_agents:
            continue
        add_check("task", rel, run_dir / rel, missing_state="pending")

    user_decision_path = run_dir / "USER_DECISION_REQUIRED.md"
    if user_decision_path.exists():
        checks.append({
            "scope": "task",
            "path": "USER_DECISION_REQUIRED.md",
            "state": "ask_user",
            "reason": "brain layer is waiting for user decision",
        })
        recommendations.append("Resolve USER_DECISION_REQUIRED.md before continuing automated brain work.")

    decisions = load_yaml(run_dir / "brain_decisions.yml").get("decisions", [])
    run_cost_entries = load_yaml(run_dir / "cost_ledger.yml").get("entries", [])
    project_cost_entries = load_yaml(project_docs / "09_COST_LEDGER.yml").get("entries", [])

    rank = {"ok": 0, "pending": 1, "warn": 2, "ask_user": 3}
    overall = "ok"
    for check in checks:
        if rank.get(check["state"], 0) > rank.get(overall, 0):
            overall = check["state"]

    counts = Counter(check["state"] for check in checks)
    return {
        "state": overall,
        "counts": dict(counts),
        "checks": checks,
        "recommendations": sorted(set(recommendations)),
        "metrics": {
            "brain_decision_count": len(decisions),
            "run_cost_entry_count": len(run_cost_entries),
            "project_cost_entry_count": len(project_cost_entries),
            "task_artifact_count": len(feedback_rules.get("required_task_artifacts", [])),
        },
        "policy_source": "config/harness_policy.yml" if policy else "missing",
    }


def detect_loop_risk(run_dir: Path, agent_name: str) -> tuple[str, str]:
    decisions = load_yaml(run_dir / "brain_decisions.yml").get("decisions", [])
    recent = [d for d in decisions if d.get("agent_name") == agent_name][-5:]
    keys = [
        (d.get("decision_type"), d.get("requested_scope"), d.get("decision"))
        for d in recent
    ]
    repeated = Counter(keys).most_common(1)
    if repeated and repeated[0][1] >= 3:
        return "stop_replan", "Repeated similar decisions suggest a possible loop; stop and replan."
    return "approve", "No loop pattern detected."


def request_traversal_decision(
    agentlab_root: Path,
    plan: WorkflowPlan,
    agent_name: str,
    requested_scope: str,
    reason: str,
    estimated_files: int,
    estimated_tokens: int,
    full_repo: bool,
) -> BrainDecision:
    configs = load_agentlab_configs(agentlab_root)
    traversal = configs.get("brain_governance", {}).get("traversal_governance", {})
    run_dir = Path(plan.run_dir)

    max_files = int(traversal.get("max_estimated_files_without_user", 200))
    max_tokens = int(traversal.get("max_estimated_tokens_without_user", 8000))
    max_full = int(traversal.get("max_full_repo_traversals_per_agent", 1))

    prior = load_yaml(run_dir / "brain_decisions.yml").get("decisions", [])
    prior_full = [
        d for d in prior
        if d.get("agent_name") == agent_name
        and d.get("decision_type") == "traversal"
        and d.get("requested_scope") == "full_repo"
    ]

    token_status = evaluate_token_status(plan, agentlab_root).get(agent_name, {})
    loop_decision, loop_reason = detect_loop_risk(run_dir, agent_name)

    decision = "approve"
    approved_scope = requested_scope
    requires_user = False
    question = ""
    reasons = [reason]

    if loop_decision == "stop_replan":
        decision = "stop_replan"
        approved_scope = "none"
        reasons.append(loop_reason)
    elif token_status.get("state") == "ask_user":
        decision = "ask_user"
        requires_user = True
        reasons.append("Agent token usage is beyond stop threshold.")
    elif full_repo and len(prior_full) >= max_full:
        decision = "ask_user"
        requires_user = True
        reasons.append("Full repository traversal was already granted for this agent.")
    elif estimated_files > max_files or estimated_tokens > max_tokens:
        decision = "ask_user"
        requires_user = True
        reasons.append("Traversal estimate exceeds automatic approval threshold.")
    elif full_repo:
        decision = "narrow_scope"
        approved_scope = "targeted_first_pass"
        reasons.append("Full repository traversal requested; start with targeted scan before expanding.")
    elif token_status.get("state") == "continue_with_warning":
        decision = "continue_with_warning"
        reasons.append("Agent is near token budget warning threshold.")

    if requires_user:
        question = (
            f"Allow {agent_name} to continue traversal scope '{requested_scope}' "
            f"for task {plan.task_id}? Reply yes/no."
        )

    brain_decision = BrainDecision(
        timestamp=utc_now(),
        project=plan.project,
        task_id=plan.task_id,
        agent_name=agent_name,
        decision_type="traversal",
        decision=decision,
        reason=" ".join(reasons),
        requested_scope="full_repo" if full_repo else requested_scope,
        approved_scope=approved_scope,
        estimated_files=estimated_files,
        estimated_tokens=estimated_tokens,
        token_budget_total=token_status.get("budget"),
        token_usage_total=token_status.get("used"),
        requires_user=requires_user,
        question=question,
        default_recommendation="yes_continue",
    )
    append_brain_decision(run_dir, brain_decision)
    if requires_user:
        write_user_decision(run_dir, brain_decision)
    return brain_decision


def request_coder_quota_decision(
    agentlab_root: Path,
    plan: WorkflowPlan,
    reason: str,
    quota_status: str,
    estimated_codex_tokens: int,
) -> BrainDecision:
    """Record that Codex Coder quota may be insufficient and ask the user."""
    configs = load_agentlab_configs(agentlab_root)
    coder_policy = configs.get("execution_policy", {}).get("coder_policy", {})
    choices = coder_policy.get("user_choices_when_quota_insufficient") or [
        "pause_until_codex_refresh",
        "delegate_remaining_coding_to_deepseek",
    ]
    run_dir = Path(plan.run_dir)
    token_status = evaluate_token_status(plan, agentlab_root).get("Coder", {})
    question = (
        "Codex quota may be insufficient for the Coder stage. Choose one: "
        f"{', '.join(choices)}."
    )

    decision = BrainDecision(
        timestamp=utc_now(),
        project=plan.project,
        task_id=plan.task_id,
        agent_name="Coder",
        decision_type="codex_quota",
        decision="ask_user",
        reason=f"{reason} Quota status: {quota_status}.",
        requested_scope="coder_execution",
        approved_scope="pending_user_decision",
        estimated_tokens=estimated_codex_tokens,
        token_budget_total=token_status.get("budget"),
        token_usage_total=token_status.get("used"),
        requires_user=True,
        question=question,
        default_recommendation=choices[0],
    )
    append_brain_decision(run_dir, decision)
    write_user_decision(run_dir, decision)
    return decision
