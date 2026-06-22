"""Provider trust policy evaluator and reporter."""

from pathlib import Path
import yaml
from typing import Dict, Any, List, Optional
from agent_runtime.capability_broker.capability_provider import CapabilityProvider

class ProviderTrustPolicy:
    def __init__(self, config_path: Optional[Path] = None):
        self.policy: Dict[str, Any] = {
            "default_trust": {
                "agentlab_owned": "trusted",
                "discovered": "provisional",
                "declared": "provisional",
                "external": "untrusted"
            },
            "risk_trust_gates": {
                "critical": "disabled",
                "high": "provisional",
                "medium": "provisional",
                "low": "trusted"
            }
        }
        if config_path and config_path.exists():
            try:
                self.policy = yaml.safe_load(config_path.read_text(encoding="utf-8")) or self.policy
            except Exception:
                pass

    def evaluate_trust(self, provider: CapabilityProvider) -> str:
        """Evaluate and return the final trust level for a provider."""
        passport = provider.passport
        
        # Explicit disabled trust level
        if passport.trust_level == "disabled":
            return "disabled"
            
        # Check defaults based on source
        source_trust = self.policy.get("default_trust", {}).get(passport.source, "provisional")
        
        # Check risk level constraints
        risk_gate = self.policy.get("risk_trust_gates", {}).get(passport.risk_level, "provisional")
        
        # Demote if risk gate is stricter
        levels = ["disabled", "untrusted", "provisional", "trusted"]
        source_idx = levels.index(source_trust)
        risk_idx = levels.index(risk_gate)
        
        final_level = levels[min(source_idx, risk_idx)]
        
        return final_level

    def generate_trust_report(self, providers: List[CapabilityProvider]) -> str:
        """Generate a markdown report summarizing trust evaluations of all providers."""
        md = []
        md.append("# Provider Trust Report")
        md.append("")
        md.append("| Provider ID | Source | Risk Level | Initial Trust | Evaluated Trust | Audition Required | Status |")
        md.append("|---|---|---|---|---|---|---|")
        
        for p in providers:
            eval_trust = self.evaluate_trust(p)
            audition = "Yes" if p.passport.verification.audition_required else "No"
            status = "✅ Active"
            if eval_trust == "disabled":
                status = "❌ Disabled"
            elif eval_trust == "untrusted":
                status = "⚠️ Quarantined"
            elif eval_trust == "provisional":
                status = "🔄 Provisional"
                
            md.append(
                f"| `{p.provider_id}` | {p.passport.source} | {p.passport.risk_level} | "
                f"{p.passport.trust_level} | **{eval_trust}** | {audition} | {status} |"
            )
            
        return "\n".join(md)
