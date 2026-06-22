"""Role coalescing logic to bundle multiple execution roles into single tasks."""

from dataclasses import dataclass, field
from typing import List, Dict, Any

@dataclass
class CoalescedPacket:
    coalesced_packet_id: str
    roles: List[str]
    selected_worker: str
    reason: List[str] = field(default_factory=list)
    risk_level: str = "medium"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "coalesced_packet_id": self.coalesced_packet_id,
            "roles": self.roles,
            "selected_worker": self.selected_worker,
            "reason": self.reason,
            "risk_level": self.risk_level
        }

def coalesce_roles(roles: List[str], task_size: str = "medium", risk_level: str = "medium") -> List[CoalescedPacket]:
    """
    Coalesce a list of roles into fewer execution packets for cost/coordination efficiency.
    """
    packets = []
    remaining_roles = set(roles)
    
    # 1. Coding/Planning bundle
    coder_roles = {"Supervisor", "PromptEngineer", "Coder", "Researcher"}
    intersect_coder = remaining_roles.intersection(coder_roles)
    if intersect_coder:
        if task_size == "small" or (task_size == "medium" and risk_level in ("low", "medium")):
            reason = [
                "small bounded patch" if task_size == "small" else "medium task with low/medium risk",
                "no separate planning worker needed",
                "one compact context pack has lower effective cost than multiple cold activations"
            ]
            packets.append(CoalescedPacket(
                coalesced_packet_id="coalesced_coder_packet",
                roles=sorted(list(intersect_coder)),
                selected_worker="claude_code",
                reason=reason,
                risk_level=risk_level
            ))
            remaining_roles.difference_update(coder_roles)
            
    # 2. Validation bundle
    validator_roles = {"TesterAuditor", "Verifier"}
    intersect_val = remaining_roles.intersection(validator_roles)
    if intersect_val:
        if task_size in ("small", "medium"):
            reason = [
                "deterministic validation is sufficient for small/medium tasks",
                "bundle test auditor and verifier into a single check workflow"
            ]
            packets.append(CoalescedPacket(
                coalesced_packet_id="coalesced_validation_packet",
                roles=sorted(list(intersect_val)),
                selected_worker="pytest",
                reason=reason,
                risk_level="low"
            ))
            remaining_roles.difference_update(validator_roles)
            
    # 3. Individual remaining roles get their own packets
    for r in sorted(list(remaining_roles)):
        worker = "claude_code"
        if r == "RepoScout":
            worker = "rg"
        elif r == "InterfaceMapper":
            worker = "ast_grep"
        elif r == "Archivist":
            worker = "git"
            
        packets.append(CoalescedPacket(
            coalesced_packet_id=f"single_{r.lower()}_packet",
            roles=[r],
            selected_worker=worker,
            reason=[f"Role {r} remains uncoalesced; runs on default worker."],
            risk_level=risk_level
        ))
        
    return packets
