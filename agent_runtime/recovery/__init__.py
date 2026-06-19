"""P2-I Execution Reliability & Failure Recovery.

This module provides deterministic failure diagnosis and recovery planning
for AgentLab task execution. When a pipeline stage fails, recovery modules
capture the failure, classify it, generate a diagnosis, and propose a
recovery plan.

Key components:
- FailureEvent: standardized failure capture structure
- FailureClassifier: deterministic classification into categories
- FailureDiagnosis: root cause hypothesis and evidence
- RecoveryPlan: human-readable recovery plan Markdown
- RetryPolicy: config-driven retry decision logic
- RecoveryVerdict: structured decision (retry/continue/rollback/stop/human_review)

All operations are safe: no destructive commands are auto-executed.
Verdicts are recommendations, not automatic actions.
"""

from __future__ import annotations

from agent_runtime.recovery.failure_event import FailureEvent, create_failure_event
from agent_runtime.recovery.failure_classifier import (
    FailureCategory,
    FailureClassifier,
    classify_failure,
)
from agent_runtime.recovery.diagnosis import (
    FailureDiagnosis,
    diagnose_failure,
)
from agent_runtime.recovery.recovery_plan import (
    RecoveryPlan,
    build_recovery_plan,
)
from agent_runtime.recovery.retry_policy import (
    RecoveryVerdict,
    RetryPolicyConfig,
    load_retry_policy,
    decide_retry_action,
    VerdictType,
)
from agent_runtime.recovery.verdict import create_verdict_from_diagnosis
from agent_runtime.recovery.human_review import (
    HumanReviewDecision,
    write_human_review_decision,
    load_latest_human_review_decision,
    load_all_human_review_decisions,
    DecisionType,
)
from agent_runtime.recovery.retry_ledger import (
    RetryAttempt,
    load_retry_attempts,
    record_retry_attempt,
    retry_attempt_count,
)
from agent_runtime.recovery.closure import build_recovery_closure_summary
from agent_runtime.recovery.resume_policy import derive_recovery_next_action
from agent_runtime.recovery.closure_feedback import (
    ClosureQualityFeedback,
    RecoveryHistoryEntry,
    derive_closure_quality_feedback,
    load_recovery_history,
    write_closure_feedback_json,
    write_closure_feedback_report,
)
from agent_runtime.recovery.alternative_route_planner import build_s6_recovery_brain_packet
from agent_runtime.recovery.capability_gap_resolver import build_capability_gap_decision_card
from agent_runtime.recovery.fake_evidence_detector import detect_fake_evidence
from agent_runtime.recovery.failure_taxonomy import S6FailureType, normalize_failure_type
from agent_runtime.recovery.strategy_search import RecoveryStrategy, search_recovery_strategy

__all__ = [
    "FailureEvent",
    "create_failure_event",
    "FailureCategory",
    "FailureClassifier",
    "classify_failure",
    "FailureDiagnosis",
    "diagnose_failure",
    "RecoveryPlan",
    "build_recovery_plan",
    "RetryPolicyConfig",
    "load_retry_policy",
    "decide_retry_action",
    "RecoveryVerdict",
    "create_verdict_from_diagnosis",
    "VerdictType",
    "HumanReviewDecision",
    "write_human_review_decision",
    "load_latest_human_review_decision",
    "load_all_human_review_decisions",
    "DecisionType",
    "RetryAttempt",
    "load_retry_attempts",
    "record_retry_attempt",
    "retry_attempt_count",
    "build_recovery_closure_summary",
    "derive_recovery_next_action",
    "ClosureQualityFeedback",
    "RecoveryHistoryEntry",
    "derive_closure_quality_feedback",
    "load_recovery_history",
    "write_closure_feedback_json",
    "write_closure_feedback_report",
    "S6FailureType",
    "normalize_failure_type",
    "RecoveryStrategy",
    "search_recovery_strategy",
    "build_capability_gap_decision_card",
    "detect_fake_evidence",
    "build_s6_recovery_brain_packet",
]
