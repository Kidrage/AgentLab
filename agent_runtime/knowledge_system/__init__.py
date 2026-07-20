"""Federated, evidence-first knowledge retrieval for AgentLab."""

from .models import (
    AuthorityLevel,
    EvidenceBundle,
    EvidenceItem,
    KnowledgeLifecycle,
    KnowledgeRecord,
    KnowledgeRequirement,
    KnowledgeSyncReceipt,
    KnowledgeTaskRequest,
    KnowledgeUpdateProposal,
    Modality,
    PreparedKnowledgeContext,
    RetrievalTrace,
    SourceRef,
    TaskRetrievalView,
)
from .migration import import_legacy_jsonl
from .operations import (
    activate_knowledge_mode,
    build_knowledge_base,
    knowledge_status,
    validate_knowledge_stage,
)
from .runtime import InsufficientEvidenceError, evaluate_outcome, prepare_task, sync_committed

__all__ = [
    "AuthorityLevel",
    "EvidenceBundle",
    "EvidenceItem",
    "KnowledgeLifecycle",
    "KnowledgeRecord",
    "KnowledgeRequirement",
    "KnowledgeSyncReceipt",
    "KnowledgeTaskRequest",
    "KnowledgeUpdateProposal",
    "InsufficientEvidenceError",
    "Modality",
    "PreparedKnowledgeContext",
    "RetrievalTrace",
    "SourceRef",
    "TaskRetrievalView",
    "activate_knowledge_mode",
    "build_knowledge_base",
    "evaluate_outcome",
    "import_legacy_jsonl",
    "knowledge_status",
    "prepare_task",
    "sync_committed",
    "validate_knowledge_stage",
]
