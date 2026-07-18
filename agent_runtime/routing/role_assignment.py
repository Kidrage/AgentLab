"""Explainable role-to-worker assignment engine."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import yaml

from agent_runtime.capabilities.capability_schema import CapabilitySchema
from agent_runtime.capabilities.compatibility import CompatibilityChecker, WorkerCapabilityRegistry
from agent_runtime.capabilities.role_requirements import RoleRequirementsRegistry
from agent_runtime.routing.approval_gate import ApprovalGate
from agent_runtime.routing.fallback_policy import WorkerFallbackPolicy
from agent_runtime.routing.mode_tier_policy import ModeTierWorkerPolicy
from agent_runtime.routing.route_decision import (
    CostEstimate,
    RejectedWorker,
    RouteConstraints,
    RouteDecision,
)
from agent_runtime.protocols import check_role_binding
from agent_runtime.workers.detector import DEFAULT_CANDIDATES
from agent_runtime.workers.performance_ledger import (
    PerformanceLedger,
    default_performance_ledger_path,
)
from agent_runtime.workers.registry import WorkerRegistry
from agent_runtime.workers.worker_card import WorkerCard


def _normalize_role(value: str) -> str:
    return value.lower().replace("_", "").replace("-", "")


class RoleAssignmentEngine:
    def __init__(self, agentlab_root: Path) -> None:
        self.root = Path(agentlab_root)
        self.schema = CapabilitySchema.load_from_file(self.root / "config" / "capability_schema.yml")
        self.roles = RoleRequirementsRegistry.load_from_file(self.root / "config" / "agent_role_requirements.yml")
        self.capabilities = WorkerCapabilityRegistry.load_from_file(self.root / "config" / "worker_capability_defaults.yml")
        self.compatibility = CompatibilityChecker(self.schema, self.roles, self.capabilities)
        self.fallback_policy = WorkerFallbackPolicy(self.root / "config" / "worker_fallback_policy.yml")
        self.mode_tier_policy = ModeTierWorkerPolicy(self.root / "config" / "mode_tier_worker_policy.yml")
        self.performance = PerformanceLedger(default_performance_ledger_path(self.root))
        self.assignment_policy = self._load_yaml(self.root / "config" / "role_assignment_policy.yml")
        self.worker_cards = {
            item["worker_id"]: WorkerCard.from_dict({
                **item,
                "installed": True,
                "authenticated": "unknown",
            })
            for item in DEFAULT_CANDIDATES
        }

    def detected_available_workers(self) -> set[str]:
        """Return cached local availability, refreshing only when no cache exists."""
        registry = WorkerRegistry(self.root / ".agentlab" / "cache")
        if not registry.load_from_cache():
            registry.scan_and_register()
        return {worker.worker_id for worker in registry.list_workers() if worker.installed}

    @staticmethod
    def _load_yaml(path: Path) -> dict:
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _configured_candidates(self, role: str) -> list[str]:
        roles = self.assignment_policy.get("roles", {})
        normalized = _normalize_role(role)
        for configured_role, config in roles.items():
            if _normalize_role(configured_role) == normalized:
                return list((config or {}).get("candidates", []) or [])
        return self.fallback_policy.candidates(role)

    def _score(self, worker_id: str, role: str, policy_index: int) -> tuple[float, float, int]:
        performance = self.performance.get_worker_performance(worker_id) or {}
        role_scores = performance.get("role_scores", {})
        score = float(role_scores.get(_normalize_role(role), 0.5))
        safety = float(performance.get("safety_score", 0.5))
        # Policy order carries a modest prior while measured performance can
        # still override it when the evidence gap is material.
        return (policy_index * 0.10 - score, -safety, policy_index)

    def assign(
        self,
        role: str,
        *,
        artifact_type: str | None = None,
        project_id: str = "AgentLab",
        phase_id: str = "unknown",
        task_id: str = "ad_hoc_route",
        mode: str = "hybrid_local_company",
        tier: str = "performance",
        available_workers: Iterable[str] | None = None,
        approved_workers: Iterable[str] | None = None,
        constraints: dict | None = None,
        extra_required_capabilities: Iterable[str] | None = None,
    ) -> RouteDecision:
        role_req = self.roles.get_role_requirements(role)
        if not role_req:
            raise ValueError(f"Unknown role: {role}")

        normalized_role = _normalize_role(role)
        normalized_artifact_type = str(artifact_type or "").strip().lower()
        artifact_expected_worker: str | None = None
        artifact_provider_id: str | None = None
        artifact_required_capabilities: list[str] = []

        def blocked_artifact_assignment(
            activation_decision: str,
            reason: str,
            required_capabilities: list[str],
        ) -> RouteDecision:
            return RouteDecision(
                project_id=project_id,
                phase_id=phase_id,
                task_id=task_id,
                role=role,
                selected_worker=None,
                selected_command=None,
                selection_reason=[reason],
                required_capabilities=required_capabilities,
                activation_decision=activation_decision,
                mode=mode,
                tier=tier,
                constraints=RouteConstraints(**(constraints or {})),
            )

        if normalized_role == "artifactproducer":
            base_required = list(role_req.required_capabilities)
            if not normalized_artifact_type:
                return blocked_artifact_assignment(
                    "blocked_artifact_type_required",
                    (
                        "ArtifactProducer is dynamically dispatched by artifact type; "
                        "generic assignment is not executable."
                    ),
                    base_required,
                )

            artifact_policy = self._load_yaml(
                self.root / "config" / "artifact_task_policy.yml"
            )
            artifact_types = artifact_policy.get("artifact_types") or {}
            if normalized_artifact_type not in artifact_types:
                return blocked_artifact_assignment(
                    "blocked_artifact_type_invalid",
                    f"unknown ArtifactProducer artifact type: {normalized_artifact_type}",
                    base_required,
                )

            from agent_runtime.protocols.artifact_task import (
                capabilities_for_artifact_type,
                route_artifact_provider,
            )

            artifact_required_capabilities = list(
                dict.fromkeys(
                    [
                        *capabilities_for_artifact_type(
                            self.root,
                            normalized_artifact_type,
                        ),
                        *(extra_required_capabilities or []),
                    ]
                )
            )
            provider_route = route_artifact_provider(
                self.root,
                normalized_artifact_type,
                required_capabilities=artifact_required_capabilities,
            )
            selected_provider = provider_route.get("selected") or {}
            artifact_expected_worker = str(
                selected_provider.get("worker") or ""
            ).strip() or None
            artifact_provider_id = str(
                selected_provider.get("provider_id") or ""
            ).strip() or None
            if provider_route.get("status") != "routed" or not artifact_expected_worker:
                return blocked_artifact_assignment(
                    "blocked_artifact_capability_mismatch",
                    (
                        "no configured provider satisfies ArtifactProducer type "
                        f"{normalized_artifact_type} and required capabilities"
                    ),
                    list(
                        dict.fromkeys(
                            [*base_required, *artifact_required_capabilities]
                        )
                    ),
                )

        from agent_runtime.control_panel.state import ControlState
        control_state = ControlState(self.root)
        
        forced_worker = None
        for w_id, w_state in control_state._state.get("workers", {}).items():
            if w_state.get("force_role") == role and w_state.get("status", "enabled") != "disabled":
                forced_worker = w_id
                break

        required = list(dict.fromkeys([
            *role_req.required_capabilities,
            *(
                artifact_required_capabilities
                if normalized_role == "artifactproducer"
                else (extra_required_capabilities or [])
            ),
        ]))
        available = (
            set(available_workers)
            if available_workers is not None
            else self.detected_available_workers()
        )
        approved = set(approved_workers or [])
        base_candidates = self._configured_candidates(role)
        candidates = self.mode_tier_policy.rank(base_candidates, role, mode, tier)
        if forced_worker:
            if forced_worker in candidates:
                candidates.remove(forced_worker)
            candidates.insert(0, forced_worker)
            
        rejected: list[RejectedWorker] = []
        eligible: list[tuple[str, int]] = []

        for index, worker_id in enumerate(candidates):
            if control_state.is_disabled("workers", worker_id):
                rejected.append(RejectedWorker(worker_id, "disabled in control panel"))
                continue
            card = self.worker_cards.get(worker_id)
            if not card:
                rejected.append(RejectedWorker(worker_id, "worker is not registered"))
                continue
            binding_allowed, binding_reason = check_role_binding(self.root, worker_id, role)
            if not binding_allowed:
                rejected.append(RejectedWorker(worker_id, f"protocol binding rejected: {binding_reason}"))
                continue
            if artifact_expected_worker and worker_id != artifact_expected_worker:
                rejected.append(
                    RejectedWorker(
                        worker_id,
                        (
                            "ArtifactTask provider policy rejected worker: "
                            f"{artifact_provider_id} requires {artifact_expected_worker} "
                            f"for {normalized_artifact_type}"
                        ),
                    )
                )
                continue
            if worker_id not in available:
                rejected.append(RejectedWorker(worker_id, "worker is unavailable"))
                continue
            compatible, reason = self.compatibility.is_compatible(worker_id, role)
            supported = set(self.capabilities.get_supported_capabilities(worker_id))
            missing_extra = [cap for cap in required if cap not in supported]
            if not compatible or missing_extra:
                detail = reason if not compatible else f"lacks task capabilities: {', '.join(missing_extra)}"
                rejected.append(RejectedWorker(worker_id, detail))
                continue
            permitted, reason = self.mode_tier_policy.permits(worker_id, card.cost_tier, mode, tier)
            if not permitted:
                rejected.append(RejectedWorker(worker_id, reason))
                continue
            eligible.append((worker_id, -1000 if worker_id == forced_worker else index))

        if not eligible:
            return RouteDecision(
                project_id=project_id,
                phase_id=phase_id,
                task_id=task_id,
                role=role,
                selected_worker=None,
                selected_command=None,
                selection_reason=["no available worker satisfies role, mode, tier, and capability constraints"],
                rejected_workers=rejected,
                required_capabilities=required,
                activation_decision="blocked_no_compatible_worker",
                mode=mode,
                tier=tier,
                fallback_workers=[],
                constraints=RouteConstraints(**(constraints or {})),
            )

        selected, _ = min(eligible, key=lambda item: self._score(item[0], role, item[1]))
        card = self.worker_cards[selected]
        approval_required, approval_reasons = ApprovalGate(self.compatibility).evaluate(
            card,
            role,
            approved_workers=approved,
        )
        fallback_candidates = self.fallback_policy.fallbacks(role, selected)
        eligible_ids = {worker for worker, _ in eligible}
        fallbacks = [worker for worker in fallback_candidates if worker in eligible_ids]
        role_score = (self.performance.get_worker_performance(selected) or {}).get("role_scores", {}).get(
            _normalize_role(role)
        )
        reasons = [
            f"satisfies required capabilities: {', '.join(required)}",
            f"preferred by {mode}/{tier} routing policy",
        ]
        if role_score is not None:
            reasons.append(f"historical {role} score: {float(role_score):.2f}")
        if selected != base_candidates[0]:
            reasons.append(f"fell back from unavailable or ineligible {base_candidates[0]}")

        return RouteDecision(
            project_id=project_id,
            phase_id=phase_id,
            task_id=task_id,
            role=role,
            selected_worker=selected,
            selected_command=card.command,
            selection_reason=reasons,
            rejected_workers=rejected,
            required_capabilities=required,
            risk_level=card.risk_level,
            approval_required=approval_required,
            approval_reasons=approval_reasons,
            activation_decision="require_approval" if approval_required else "activate",
            mode=mode,
            tier=tier,
            cost_estimate=CostEstimate(
                known=card.cost_tier == "free",
                policy="approval_required" if approval_required else "within_policy",
                tier=card.cost_tier,
            ),
            fallback_workers=fallbacks,
            constraints=RouteConstraints(**(constraints or {})),
        )


def assign_role(role: str, agentlab_root: Path, **kwargs) -> dict:
    """Functional API returning the wrapped route-decision schema."""
    return RoleAssignmentEngine(agentlab_root).assign(role, **kwargs).to_dict()
