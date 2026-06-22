"""Activation plan compiler for execution economy."""

from pathlib import Path
import yaml
from typing import Dict, Any, List, Optional
import os

from agent_runtime.execution_economy.activation_cost import (
    ActivationCost, FixedStartupCost, CacheProfile, VariableCost, NonTokenCosts
)
from agent_runtime.execution_economy.cache_profile import calculate_cache_profile
from agent_runtime.execution_economy.effective_cost import (
    calculate_effective_tokens, estimate_cost_in_usd, get_cost_tier
)
from agent_runtime.execution_economy.marginal_utility_gate import evaluate_marginal_utility
from agent_runtime.execution_economy.role_activation_policy import RoleActivationPolicy
from agent_runtime.execution_economy.role_coalescing import coalesce_roles
from agent_runtime.execution_economy.context_reuse_policy import ContextReusePolicy
from agent_runtime.execution_economy.escalation_ladder import EscalationLadder
from agent_runtime.execution_economy.activation_decision import (
    ActivationDecision, DecisionCost, CacheVerdict, ExpectedBenefit, DecisionContextBudget
)
from agent_runtime.execution_economy.renderer import render_execution_economy_report

# Default worker activation costs database
DEFAULT_WORKER_COSTS = {
    "claude_code": {
        "fixed_startup_cost": {
            "raw_prompt_tokens": 12000,
            "cacheable_prompt_tokens": 9500,
            "expected_cache_hit_rate": 0.85,
            "effective_prompt_tokens": 2500,
            "estimated_cached_input_discount": "high",
            "estimated_latency_s": 8.0,
            "operator_friction": "medium"
        },
        "cache_profile": {
            "stable_prefix_hash": "sha256:role-skill-prefix",
            "skill_context_hash": "sha256:approved-skill-set",
            "mcp_manifest_hash": "sha256:declared-mcp-passports",
            "last_cache_hit_observed": "unknown",
            "cache_confidence": "medium"
        },
        "variable_cost": {
            "task_specific_context_tokens": 3000,
            "context_tokens_per_kb": 180,
            "output_tokens_expected": 2000,
            "dollars_per_call": "unknown"
        },
        "non_token_costs": {
            "coordination_cost": "medium",
            "permission_risk": "high",
            "state_mutation_risk": "high"
        },
        "hidden_costs": ["context_duplication", "handoff_interpretation", "diff_conflict_risk"],
        "confidence": "medium"
    },
    "rg": {
        "fixed_startup_cost": {
            "raw_prompt_tokens": 0,
            "cacheable_prompt_tokens": 0,
            "expected_cache_hit_rate": 0.0,
            "effective_prompt_tokens": 0,
            "estimated_cached_input_discount": "none",
            "estimated_latency_s": 0.1,
            "operator_friction": "low"
        },
        "cache_profile": {
            "stable_prefix_hash": None,
            "skill_context_hash": None,
            "mcp_manifest_hash": None,
            "last_cache_hit_observed": "false",
            "cache_confidence": "high"
        },
        "variable_cost": {
            "task_specific_context_tokens": 0,
            "context_tokens_per_kb": 0,
            "output_tokens_expected": 0,
            "dollars_per_call": "0"
        },
        "non_token_costs": {
            "coordination_cost": "low",
            "permission_risk": "low",
            "state_mutation_risk": "low"
        },
        "hidden_costs": [],
        "confidence": "high"
    },
    "git": {
        "fixed_startup_cost": {
            "raw_prompt_tokens": 0,
            "cacheable_prompt_tokens": 0,
            "expected_cache_hit_rate": 0.0,
            "effective_prompt_tokens": 0,
            "estimated_cached_input_discount": "none",
            "estimated_latency_s": 0.5,
            "operator_friction": "low"
        },
        "cache_profile": {
            "stable_prefix_hash": None,
            "skill_context_hash": None,
            "mcp_manifest_hash": None,
            "last_cache_hit_observed": "false",
            "cache_confidence": "high"
        },
        "variable_cost": {
            "task_specific_context_tokens": 0,
            "context_tokens_per_kb": 0,
            "output_tokens_expected": 0,
            "dollars_per_call": "0"
        },
        "non_token_costs": {
            "coordination_cost": "low",
            "permission_risk": "low",
            "state_mutation_risk": "low"
        },
        "hidden_costs": [],
        "confidence": "high"
    },
    "pytest": {
        "fixed_startup_cost": {
            "raw_prompt_tokens": 0,
            "cacheable_prompt_tokens": 0,
            "expected_cache_hit_rate": 0.0,
            "effective_prompt_tokens": 0,
            "estimated_cached_input_discount": "none",
            "estimated_latency_s": 2.0,
            "operator_friction": "low"
        },
        "cache_profile": {
            "stable_prefix_hash": None,
            "skill_context_hash": None,
            "mcp_manifest_hash": None,
            "last_cache_hit_observed": "false",
            "cache_confidence": "high"
        },
        "variable_cost": {
            "task_specific_context_tokens": 0,
            "context_tokens_per_kb": 0,
            "output_tokens_expected": 0,
            "dollars_per_call": "0"
        },
        "non_token_costs": {
            "coordination_cost": "low",
            "permission_risk": "low",
            "state_mutation_risk": "low"
        },
        "hidden_costs": [],
        "confidence": "high"
    },
    "ruff": {
        "fixed_startup_cost": {
            "raw_prompt_tokens": 0,
            "cacheable_prompt_tokens": 0,
            "expected_cache_hit_rate": 0.0,
            "effective_prompt_tokens": 0,
            "estimated_cached_input_discount": "none",
            "estimated_latency_s": 0.5,
            "operator_friction": "low"
        },
        "cache_profile": {
            "stable_prefix_hash": None,
            "skill_context_hash": None,
            "mcp_manifest_hash": None,
            "last_cache_hit_observed": "false",
            "cache_confidence": "high"
        },
        "variable_cost": {
            "task_specific_context_tokens": 0,
            "context_tokens_per_kb": 0,
            "output_tokens_expected": 0,
            "dollars_per_call": "0"
        },
        "non_token_costs": {
            "coordination_cost": "low",
            "permission_risk": "low",
            "state_mutation_risk": "low"
        },
        "hidden_costs": [],
        "confidence": "high"
    },
    "ast_grep": {
        "fixed_startup_cost": {
            "raw_prompt_tokens": 0,
            "cacheable_prompt_tokens": 0,
            "expected_cache_hit_rate": 0.0,
            "effective_prompt_tokens": 0,
            "estimated_cached_input_discount": "none",
            "estimated_latency_s": 0.5,
            "operator_friction": "low"
        },
        "cache_profile": {
            "stable_prefix_hash": None,
            "skill_context_hash": None,
            "mcp_manifest_hash": None,
            "last_cache_hit_observed": "false",
            "cache_confidence": "high"
        },
        "variable_cost": {
            "task_specific_context_tokens": 0,
            "context_tokens_per_kb": 0,
            "output_tokens_expected": 0,
            "dollars_per_call": "0"
        },
        "non_token_costs": {
            "coordination_cost": "low",
            "permission_risk": "low",
            "state_mutation_risk": "low"
        },
        "hidden_costs": [],
        "confidence": "high"
    }
}

def load_worker_costs(config_path: Optional[Path] = None) -> Dict[str, Any]:
    if config_path and config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            if "workers" in data:
                return data["workers"]
        except Exception:
            pass
    return DEFAULT_WORKER_COSTS

def compile_activation_plan(task_packet_path: Path, agentlab_root: Path) -> Dict[str, Any]:
    """Compile the entire cache-aware execution economy activation plan."""
    packet_path = Path(task_packet_path)
    if not packet_path.exists():
        raise FileNotFoundError(f"Task packet not found at {packet_path}")
        
    try:
        packet_data = yaml.safe_load(packet_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        raise ValueError(f"Invalid YAML in task packet: {e}")
        
    # Standard task packet layout can have top-level task_packet or not
    tp = packet_data.get("task_packet", packet_data)
    project_id = tp.get("project_id", "AgentLab")
    phase_id = tp.get("phase_id", "unknown")
    task_id = tp.get("packet_id", f"{project_id}_{phase_id}_task")
    objective = tp.get("objective", "")
    
    # Estimate task size
    task_size = "medium"
    if "small" in objective.lower() or len(objective) < 100:
        task_size = "small"
    elif len(objective) > 1000:
        task_size = "large"
        
    # Output directories
    out_dir = agentlab_root / "projects" / project_id / "execution_economy"
    decisions_dir = out_dir / "activation_decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    
    # Load policies
    role_policy = RoleActivationPolicy(agentlab_root / "config" / "role_activation_policy.yml")
    worker_costs = load_worker_costs(agentlab_root / "config" / "worker_activation_costs.yml")
    context_policy = ContextReusePolicy(agentlab_root / "config" / "context_cache_policy.yml")
    escalation_ladder = EscalationLadder(agentlab_root / "config" / "escalation_ladders.yml")
    
    roles = [
        "Supervisor", "RepoScout", "InterfaceMapper", "Researcher",
        "PromptEngineer", "Coder", "TesterAuditor", "Verifier", "Archivist"
    ]
    
    decisions_dict = []
    total_raw_tokens = 0
    total_effective_tokens = 0
    total_raw_usd = 0.0
    total_effective_usd = 0.0
    
    cache_profile_reports = {}
    context_reuse_plans = {}
    
    for role in roles:
        worker_id = role_policy.get_candidate_worker(role)
        
        # Load worker cost template
        w_cost_dict = worker_costs.get(worker_id, DEFAULT_WORKER_COSTS.get("claude_code"))
        act_cost = ActivationCost.from_dict({"worker_id": worker_id, **w_cost_dict})
        
        # Calculate cache profile dynamically
        cp = calculate_cache_profile(worker_id)
        act_cost.cache_profile = cp
        
        # Calculate effective tokens & usd
        effective_tokens = calculate_effective_tokens(act_cost)
        act_cost.fixed_startup_cost.effective_prompt_tokens = effective_tokens
        
        raw_tokens = act_cost.fixed_startup_cost.raw_prompt_tokens + act_cost.variable_cost.task_specific_context_tokens
        raw_usd = estimate_cost_in_usd(raw_tokens, worker_id)
        eff_usd = estimate_cost_in_usd(effective_tokens, worker_id)
        
        total_raw_tokens += raw_tokens
        total_effective_tokens += effective_tokens
        total_raw_usd += raw_usd
        total_effective_usd += eff_usd
        
        # Marginal utility check
        benefits = role_policy.get_expected_benefit(role, task_size)
        decision, verdict, reasons = evaluate_marginal_utility(act_cost, benefits, task_size)
        
        # Build Context Budget
        budget = context_policy.get_budget_for_worker(worker_id)
        
        # Construct ActivationDecision object
        dec = ActivationDecision(
            project_id=project_id,
            phase_id=phase_id,
            task_id=task_id,
            role=role,
            candidate_worker=worker_id,
            decision=decision,
            activation_temperature="warm_cached" if verdict == "justified" else "deterministic" if worker_id in ("rg", "git", "pytest", "ruff", "ast_grep") else "cold",
            satisfied_by=[f"deterministic_{role.lower()}"] if decision in ("satisfy_by_deterministic", "satisfy_by_cache") else [],
            selected_worker=worker_id if decision in ("spawn", "coalesce") else None,
            selected_provider="local_cli" if decision in ("spawn", "coalesce") else None,
            activation_cost=DecisionCost(
                raw_tokens=raw_tokens,
                cacheable_tokens=act_cost.fixed_startup_cost.cacheable_prompt_tokens,
                effective_tokens=effective_tokens,
                estimated_usd=raw_usd,
                effective_estimated_usd=get_cost_tier(eff_usd),
                latency_class="low" if act_cost.fixed_startup_cost.estimated_latency_s < 1.0 else "medium" if act_cost.fixed_startup_cost.estimated_latency_s < 5.0 else "high",
                coordination_cost=act_cost.non_token_costs.coordination_cost,
                permission_risk=act_cost.non_token_costs.permission_risk,
                state_mutation_risk=act_cost.non_token_costs.state_mutation_risk
            ),
            cache_verdict=CacheVerdict(
                expected="hit" if cp.cache_confidence == "high" else "partial_hit" if cp.cache_confidence == "medium" else "miss",
                confidence=cp.cache_confidence,
                evidence=["stable role/skill prefix reused", "read-only review packet"] if cp.cache_confidence in ("high", "medium") else []
            ),
            expected_benefit=ExpectedBenefit(
                quality_gain=benefits.get("quality_gain", "none"),
                risk_reduction=benefits.get("risk_reduction", "none"),
                speed_gain=benefits.get("speed_gain", "none"),
                recovery_value=benefits.get("recovery_value", "none")
            ),
            marginal_utility_verdict=verdict,
            reason=reasons,
            context_budget=DecisionContextBudget(
                max_raw_tokens=budget.max_raw_tokens,
                max_effective_tokens=budget.max_effective_tokens,
                required_assets=budget.required_assets,
                excluded_assets=budget.excluded_assets
            ),
            evidence_paths=[str(packet_path)]
        )
        
        decisions_dict.append(dec.to_dict())
        
        # Save decision for this role
        role_file = decisions_dir / f"{role.lower()}.yml"
        role_file.write_text(yaml.safe_dump(dec.to_dict(), sort_keys=False), encoding="utf-8")
        
        cache_profile_reports[role] = act_cost.cache_profile.last_cache_hit_observed
        context_reuse_plans[role] = dec.context_budget.to_dict()

    # Coalescing
    coalesced = coalesce_roles([d["role"] for d in decisions_dict if d["decision"] == "spawn"], task_size)
    coalesced_list = [p.to_dict() for p in coalesced]
    
    # Save Coalescing Report
    coalesce_file = out_dir / "role_coalescing.yml"
    coalesce_file.write_text(yaml.safe_dump({"role_coalescing": coalesced_list}, sort_keys=False), encoding="utf-8")
    
    # Save Context Reuse Plan
    context_file = out_dir / "context_reuse_plan.yml"
    context_file.write_text(yaml.safe_dump({"context_reuse_plans": context_reuse_plans}, sort_keys=False), encoding="utf-8")
    
    # Save Cache Profile Report
    cache_file = out_dir / "cache_profile_report.yml"
    cache_file.write_text(yaml.safe_dump({"cache_profile_report": cache_profile_reports}, sort_keys=False), encoding="utf-8")
    
    # Save Escalation Ladder
    esc_file = out_dir / "escalation_ladder.yml"
    esc_file.write_text(yaml.safe_dump({"escalation_ladder": escalation_ladder.to_dict()}, sort_keys=False), encoding="utf-8")
    
    # Generate overall Activation Plan
    plan = {
        "activation_plan": {
            "project_id": project_id,
            "task_id": task_id,
            "task_size": task_size,
            "decisions": decisions_dict,
            "coalesced_packets": coalesced_list,
            "totals": {
                "raw_tokens": total_raw_tokens,
                "effective_tokens": total_effective_tokens,
                "raw_usd": total_raw_usd,
                "effective_usd": total_effective_usd
            }
        }
    }
    
    plan_file = out_dir / "activation_plan.yml"
    plan_file.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    
    # Generate MD Report
    report_md = render_execution_economy_report(
        project_id, task_id, decisions_dict, coalesced_list,
        total_raw_tokens, total_effective_tokens, total_raw_usd, total_effective_usd
    )
    report_file = out_dir / "execution_economy_report.md"
    report_file.write_text(report_md, encoding="utf-8")
    
    return plan
