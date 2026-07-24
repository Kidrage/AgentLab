"""Deterministic, fail-closed input classification for Task Runtime v2."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import yaml


_TIER_ORDER = ("L0", "L1", "L2", "L3")
_KNOWN_FIELDS = {
    "kind",
    "scope",
    "target_count",
    "canon_impact",
    "risk_flags",
    "requested_tier",
}
_REQUIRED_FIELDS = {
    "kind",
    "scope",
    "target_count",
    "canon_impact",
    "risk_flags",
}


class TaskInputClassifier:
    """Classify declared task facts into one non-downgradable execution route."""

    def __init__(self, agentlab_root: Path) -> None:
        root = Path(agentlab_root).resolve(strict=False)
        policy_path = root / "config" / "task_input_tiers.yml"
        if not policy_path.is_file():
            policy_path = Path(__file__).resolve().parents[2] / "config" / "task_input_tiers.yml"
        policy = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
        if not isinstance(policy, dict):
            raise ValueError("task input tier policy must be a mapping")
        tiers = policy.get("tiers") or {}
        classification = policy.get("classification") or {}
        if set(tiers) != set(_TIER_ORDER) or not isinstance(classification, dict):
            raise ValueError("task input tier policy must define L0 through L3")
        self._tiers = tiers
        self._classification = classification
        self._trace_record_contracts = policy.get("trace_record_contracts") or {}
        self._sealed_source_policy = policy.get("sealed_source_policy") or {}

    def classify(self, profile: Mapping[str, Any] | None) -> dict[str, Any]:
        """Return a serializable route decision derived only from declared facts."""

        missing_profile = profile is None or not profile
        if profile is not None and not isinstance(profile, Mapping):
            raise ValueError("input profile must be a mapping")
        raw = dict(profile or {})
        unknown_fields = sorted(set(raw) - _KNOWN_FIELDS)
        missing_fields = sorted(_REQUIRED_FIELDS - set(raw))
        target_count = raw.get("target_count", 0)
        if isinstance(target_count, bool) or not isinstance(target_count, int):
            raise ValueError("target_count must be a non-negative integer")
        if target_count < 0:
            raise ValueError("target_count must be a non-negative integer")
        risk_flags = raw.get("risk_flags") or []
        if not isinstance(risk_flags, list) or any(
            not isinstance(flag, str) or not flag.strip() for flag in risk_flags
        ):
            raise ValueError("risk_flags must be a list of non-empty strings")

        normalized = {
            "kind": str(raw.get("kind") or "unclassified").strip().lower(),
            "scope": str(raw.get("scope") or "unknown").strip().lower(),
            "target_count": target_count,
            "canon_impact": str(raw.get("canon_impact") or "unknown").strip().lower(),
            "risk_flags": sorted(set(flag.strip().lower() for flag in risk_flags)),
        }
        requested_tier = str(raw.get("requested_tier") or "").strip().upper()
        escalation_reasons: list[str] = []
        required_level = 0

        if missing_profile:
            required_level = 3
            escalation_reasons.append("missing_input_profile")
        if missing_fields:
            required_level = 3
            escalation_reasons.extend(
                f"missing_required_fact:{field}" for field in missing_fields
            )
        if unknown_fields:
            required_level = 3
            escalation_reasons.append("unknown_profile_fields")

        required_level = max(
            required_level,
            self._minimum_level(
                "kind_minimum", normalized["kind"], "unknown_kind", escalation_reasons
            ),
            self._minimum_level(
                "scope_minimum", normalized["scope"], "unknown_scope", escalation_reasons
            ),
            self._minimum_level(
                "canon_impact_minimum",
                normalized["canon_impact"],
                "unknown_canon_impact",
                escalation_reasons,
            ),
        )

        risk_minimum = self._classification.get("risk_minimum") or {}
        for flag in normalized["risk_flags"]:
            tier = risk_minimum.get(flag)
            if tier not in _TIER_ORDER:
                required_level = 3
                escalation_reasons.append(f"unknown_risk_flag:{flag}")
            else:
                required_level = max(required_level, _TIER_ORDER.index(tier))

        limits = self._classification.get("target_count") or {}
        if target_count > int(limits.get("l2_max", 3)):
            required_level = 3
            escalation_reasons.append("target_count_exceeds_local_limit")
        elif target_count > int(limits.get("l0_max", 1)):
            required_level = max(required_level, 1)

        if requested_tier:
            if requested_tier not in _TIER_ORDER:
                required_level = 3
                escalation_reasons.append("unknown_requested_tier")
            else:
                requested_level = _TIER_ORDER.index(requested_tier)
                if requested_level < required_level:
                    escalation_reasons.append("requested_tier_below_required")
                required_level = max(required_level, requested_level)

        tier = _TIER_ORDER[required_level]
        decision = deepcopy(self._tiers[tier])
        admission_ready = not any(
            reason == "missing_input_profile"
            or reason.startswith("missing_required_fact:")
            or reason.startswith("unknown_")
            for reason in escalation_reasons
        )
        return {
            "schema_version": "task-input-classification/v1",
            "tier": tier,
            "label": str(decision["label"]),
            "route": str(decision["route"]),
            "worker_limit": decision.get("worker_limit"),
            "delegation_mode": str(decision["delegation_mode"]),
            "minimum_successful_delegated_attempts": int(
                decision["minimum_successful_delegated_attempts"]
            ),
            "pre_worker_records": list(decision.get("pre_worker_records") or []),
            "brain_decision_required": bool(decision["brain_decision_required"]),
            "full_audit_required": bool(decision["full_audit_required"]),
            "validation_gates": list(decision.get("validation_gates") or []),
            "required_records": list(decision.get("required_records") or []),
            "gate_evidence": dict(decision.get("gate_evidence") or {}),
            "admission_ready": admission_ready,
            "enforcement": "strict",
            "normalized_profile": normalized,
            "escalation_reasons": sorted(set(escalation_reasons)),
        }

    def trace_record_contract(self, record_type: str) -> dict[str, Any]:
        """Return one governed trace-record contract from the policy authority."""

        contract = self._trace_record_contracts.get(str(record_type))
        if not isinstance(contract, dict):
            raise ValueError(f"unknown trace record type: {record_type}")
        return deepcopy(contract)

    def sealed_source_policy(self) -> dict[str, Any]:
        """Return the governed outbound-source boundary."""

        policy = deepcopy(self._sealed_source_policy)
        if not isinstance(policy, dict) or not policy:
            raise ValueError("task input tier policy must define sealed_source_policy")
        return policy

    def _minimum_level(
        self,
        policy_key: str,
        value: str,
        unknown_reason: str,
        escalation_reasons: list[str],
    ) -> int:
        tier = (self._classification.get(policy_key) or {}).get(value)
        if tier not in _TIER_ORDER:
            escalation_reasons.append(unknown_reason)
            return 3
        return _TIER_ORDER.index(tier)
