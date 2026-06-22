"""Markdown renderer for execution economy reports."""

from typing import List, Dict, Any

def render_execution_economy_report(
    project_id: str,
    task_id: str,
    decisions: List[Dict[str, Any]],
    coalesced_packets: List[Dict[str, Any]],
    total_raw_tokens: int,
    total_effective_tokens: int,
    total_raw_usd: float,
    total_effective_usd: float
) -> str:
    """Generate a clean, beautiful Markdown report for execution economy."""
    savings_tokens = total_raw_tokens - total_effective_tokens
    savings_usd = total_raw_usd - total_effective_usd
    savings_pct = (savings_tokens / total_raw_tokens * 100) if total_raw_tokens > 0 else 0
    
    md = []
    md.append(f"# Execution Economy Report — {project_id}")
    md.append(f"**Task ID:** {task_id}")
    md.append("")
    md.append("## Economy Summary")
    md.append("| Metric | Raw / Worst Case | Cache-Aware / Effective | Savings | % Discount |")
    md.append("|---|---|---|---|---|")
    md.append(f"| **Tokens** | {total_raw_tokens:,} | {total_effective_tokens:,} | {savings_tokens:,} | {savings_pct:.1f}% |")
    md.append(f"| **Cost (USD)** | ${total_raw_usd:.4f} | ${total_effective_usd:.4f} | ${savings_usd:.4f} | {savings_pct:.1f}% |")
    md.append("")
    
    md.append("## Role Decisions")
    md.append("| Role | Candidate | Decision | Verdict | Expected Benefit | Effective Cost | Reason |")
    md.append("|---|---|---|---|---|---|---|")
    for d in decisions:
        role = d.get("role", "")
        cand = d.get("candidate_worker", "")
        decision = d.get("decision", "")
        verdict = d.get("marginal_utility_verdict", "")
        
        # expected benefit summary
        eb = d.get("expected_benefit", {})
        eb_summary = f"Q:{eb.get('quality_gain')} / R:{eb.get('risk_reduction')}"
        
        # effective cost summary
        ac = d.get("activation_cost", {})
        eff_cost = f"{ac.get('effective_tokens', 0):,} tokens"
        
        reasons = ", ".join(d.get("reason", []))
        md.append(f"| {role} | {cand} | **{decision}** | {verdict} | {eb_summary} | {eff_cost} | {reasons} |")
    
    md.append("")
    md.append("## Role Coalescing Packets")
    if coalesced_packets:
        for p in coalesced_packets:
            md.append(f"### Packet: {p.get('coalesced_packet_id')}")
            md.append(f"- **Roles:** {', '.join(p.get('roles', []))}")
            md.append(f"- **Selected Worker:** {p.get('selected_worker')}")
            md.append(f"- **Risk Level:** {p.get('risk_level')}")
            md.append("- **Reasons:**")
            for r in p.get("reason", []):
                md.append(f"  - {r}")
            md.append("")
    else:
        md.append("No coalesced packets generated.")
        
    md.append("")
    md.append("## Escalation Rules & Triggers")
    md.append("- **Initial Entry:** Deterministic Scan / Check")
    md.append("- **Escalation Triggers:**")
    md.append("  - `if_missing_context` -> api_supervisor_compact")
    md.append("  - `if_patch_needed` -> single_cli_coder")
    md.append("  - `if_tests_fail` -> cached_failure_analyzer")
    md.append("  - `if_diff_high_risk` -> cached_or_strong_llm_verifier")
    
    return "\n".join(md)
