"""Capability provider routing logic based on priority, trust, and cost."""

from typing import List, Dict, Any, Optional, Tuple
from agent_runtime.capability_broker.broker_registry import BrokerRegistry
from agent_runtime.capability_broker.provider_trust import ProviderTrustPolicy
from agent_runtime.capability_broker.capability_provider import CapabilityProvider

# Priority ranking of provider types (lower is higher priority)
PROVIDER_TYPE_PRIORITY = {
    "agentlab_owned_tool": 1,
    "agentlab_owned_skill": 2,
    "agentlab_brokered_mcp": 3,
    "direct_api_provider": 4,
    "worker_local_skill": 5,
    "worker_local_mcp": 6,
    "external_handoff_provider": 7
}

def route_capability(
    capability: str,
    registry: BrokerRegistry,
    trust_policy: ProviderTrustPolicy,
    project_id: str = "AgentLab"
) -> Tuple[Optional[CapabilityProvider], Dict[str, Any]]:
    """
    Route a capability request to the optimal capability provider.
    Returns (selected_provider, routing_decision_info).
    """
    candidates = registry.get_providers_for_capability(capability)
    eligible = []
    
    reasons = []
    
    for c in candidates:
        if not c.is_eligible_for_project(project_id):
            reasons.append(f"Provider {c.provider_id} is not eligible for project {project_id}.")
            continue
            
        trust = trust_policy.evaluate_trust(c)
        if trust in ("disabled", "untrusted"):
            reasons.append(f"Provider {c.provider_id} was filtered out due to trust status ({trust}).")
            continue
            
        eligible.append((c, trust))
        
    if not eligible:
        return None, {
            "capability": capability,
            "selected_provider": None,
            "status": "failed",
            "routing_reasons": reasons
        }
        
    # Sort eligible by type priority first, then trust level (trusted > provisional), then cost model (cheaper is better)
    def sort_key(item):
        provider, trust = item
        priority = PROVIDER_TYPE_PRIORITY.get(provider.passport.provider_type, 99)
        trust_val = 0 if trust == "trusted" else 1
        cost = provider.passport.cost_model.estimated_usd
        return (priority, trust_val, cost)
        
    sorted_eligible = sorted(eligible, key=sort_key)
    best_provider, best_trust = sorted_eligible[0]
    
    decision_info = {
        "capability": capability,
        "selected_provider": best_provider.provider_id,
        "selected_provider_type": best_provider.passport.provider_type,
        "trust_level": best_trust,
        "invocation_mode": best_provider.passport.invocation_mode,
        "risk_level": best_provider.passport.risk_level,
        "estimated_usd": best_provider.passport.cost_model.estimated_usd,
        "status": "success",
        "routing_reasons": [
            f"Selected best candidate {best_provider.provider_id} with priority level {best_provider.passport.provider_type}."
        ]
    }
    
    return best_provider, decision_info
