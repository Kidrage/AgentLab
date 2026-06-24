from pathlib import Path
from agent_runtime.approvals.approval_ledger import load_approval_ledger, write_approval_ledger

def control_approve(project_root: Path, project: str, decision_id: str, actor: str, reason: str) -> bool:
    path = project_root / "memory" / project / "approval_ledger.yml"
    ledger = load_approval_ledger(path)
    if ledger.approve_decision(decision_id, actor, reason):
        write_approval_ledger(ledger, path)
        return True
    return False

def control_reject(project_root: Path, project: str, decision_id: str, actor: str, reason: str) -> bool:
    path = project_root / "memory" / project / "approval_ledger.yml"
    ledger = load_approval_ledger(path)
    if ledger.reject_decision(decision_id, actor, reason):
        write_approval_ledger(ledger, path)
        return True
    return False
