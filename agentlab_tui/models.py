from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict

@dataclass
class TUIWarning:
    message: str

@dataclass
class TUICommandResult:
    action: str
    status: str
    message: str
    requires_approval: bool = False
    mutated_state: bool = False
    evidence_path: Optional[str] = None
    warnings: List[TUIWarning] = field(default_factory=list)

@dataclass
class TUIStateSnapshot:
    project_id: Optional[str] = None
    view: str = "overview"
    workers: List[Dict[str, Any]] = field(default_factory=list)
    tasks: List[Dict[str, Any]] = field(default_factory=list)
    approvals: List[Dict[str, Any]] = field(default_factory=list)
    costs: Dict[str, Any] = field(default_factory=dict)
    warnings: List[TUIWarning] = field(default_factory=list)

@dataclass
class TUIView:
    name: str

@dataclass
class TUIAction:
    name: str
