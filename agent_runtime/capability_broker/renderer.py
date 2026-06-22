"""Markdown renderer for capability broker reports."""

from typing import List, Dict, Any

def render_provider_routing_plan(
    capability: str,
    decision_info: Dict[str, Any]
) -> str:
    """Generate a markdown report for a routed capability plan."""
    md = []
    md.append(f"# Capability Routing Plan — {capability}")
    md.append("")
    md.append(f"- **Requested Capability:** {capability}")
    
    if decision_info.get("selected_provider"):
        md.append(f"- **Selected Provider:** `{decision_info.get('selected_provider')}`")
        md.append(f"- **Provider Type:** {decision_info.get('selected_provider_type')}")
        md.append(f"- **Trust Level:** {decision_info.get('trust_level')}")
        md.append(f"- **Invocation Mode:** {decision_info.get('invocation_mode')}")
        md.append(f"- **Risk Level:** {decision_info.get('risk_level')}")
        md.append(f"- **Estimated USD Cost:** ${decision_info.get('estimated_usd', 0.0):.4f}")
        md.append("- **Routing Verdict:** Success")
    else:
        md.append("- **Routing Verdict:** Failed (No eligible provider found)")
        
    md.append("")
    md.append("## Decision Logs & Rationale")
    for reason in decision_info.get("routing_reasons", []):
        md.append(f"- {reason}")
        
    return "\n".join(md)
