"""Media generation route selection and contract building."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_runtime.config_loader import load_yaml


MEDIA_DOMAINS = {
    "image_generation",
    "image_editing",
    "video_generation",
    "video_editing",
    "multimodal_asset_generation",
}


def build_media_generation_contract(
    *,
    prompt: str,
    mission_domain: str,
    project_id: str | None,
    task_id: str | None,
    root: Path,
) -> dict[str, Any]:
    """Build a non-executing media generation routing contract."""
    config = load_yaml(root / "config" / "media_generation_backends.yml")
    backends = _backends(config)
    intent = _intent_for_domain(mission_domain)
    modality = _modality_for_domain(mission_domain, prompt)
    quality_target = _quality_target(prompt)
    cost_policy = _cost_policy(prompt)
    policy_key = _policy_key(prompt, quality_target)
    configured_chain = _policy_chain(config, policy_key)
    fallback_chain = _filter_chain(configured_chain, backends, modality)
    selected_backend = _select_executable_backend(fallback_chain, backends)

    approval = _approval_card(selected_backend, backends) if selected_backend else None
    pending = _pending_backends(fallback_chain, backends)
    executable = selected_backend is not None and approval is None

    artifact_root = (
        f"projects/{project_id}/runs/{task_id}/artifacts/"
        if project_id and task_id
        else "projects/<Project>/runs/<task_id>/artifacts/"
    )

    contract: dict[str, Any] = {
        "schema_version": 1,
        "contract_type": "media_generation_contract",
        "project_id": project_id,
        "task_id": task_id,
        "intent": intent,
        "modality": modality,
        "quality_target": quality_target,
        "cost_policy": cost_policy,
        "time_policy": _time_policy(prompt),
        "prompt": prompt,
        "reference_assets": [],
        "style_constraints": _style_constraints(prompt),
        "delivery_constraints": _delivery_constraints(prompt),
        "backend_policy": policy_key,
        "selected_backend": selected_backend,
        "executable": executable,
        "fallback_chain": fallback_chain,
        "pending_backends": pending,
        "approval_required": approval is not None,
        "approval_card": approval,
        "artifact_paths": {
            "run_artifacts": artifact_root,
            "artifact_manifest": f"{artifact_root}artifact_manifest.yml",
            "generation_ledger": f"{artifact_root}generation_ledger.yml",
            "media_qc_report": f"{artifact_root}media_qc_report.yml",
            "production_artifacts": (
                f"projects/{project_id}/artifacts/" if project_id else "projects/<Project>/artifacts/"
            ),
        },
        "acceptance_gates": [
            "capability_auth_quota_preflight",
            "prompt_and_parameters_recorded",
            "artifact_manifest_written",
            "generation_ledger_written",
            "media_qc_report_written",
            "qa_or_human_acceptance_before_project_artifact_promotion",
            "project_handoff_refreshed_after_material_change",
        ],
        "harness_rules": _harness_rules(selected_backend, backends),
        "no_backend_fallback": {
            "action": "write_tool_handoff_and_route_proposal",
            "do_not_fabricate_artifact": True,
        },
        "backend_contracts": {
            backend_id: _public_backend_contract(backend)
            for backend_id, backend in backends.items()
            if backend_id in fallback_chain or backend.get("auth_state") == "pending_activation"
        },
    }
    return contract


def is_media_generation_domain(mission_domain: str) -> bool:
    return mission_domain in MEDIA_DOMAINS


def _backends(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = config.get("backends", {}) if isinstance(config, dict) else {}
    return values if isinstance(values, dict) else {}


def _policy_chain(config: dict[str, Any], policy_key: str) -> list[str]:
    policies = config.get("policies", {}) if isinstance(config, dict) else {}
    policy = policies.get(policy_key, {}) if isinstance(policies, dict) else {}
    chain = policy.get("backend_chain", []) if isinstance(policy, dict) else []
    return [str(item) for item in chain] if isinstance(chain, list) else []


def _filter_chain(
    chain: list[str],
    backends: dict[str, dict[str, Any]],
    modality: str,
) -> list[str]:
    filtered = []
    for backend_id in chain:
        backend = backends.get(backend_id, {})
        modalities = backend.get("modalities", [])
        if "mixed" in modalities or modality in modalities:
            filtered.append(backend_id)
    return filtered


def _select_executable_backend(
    chain: list[str],
    backends: dict[str, dict[str, Any]],
) -> str | None:
    for backend_id in chain:
        backend = backends.get(backend_id, {})
        if backend.get("auth_state") != "ready":
            continue
        return backend_id
    return None


def _approval_card(selected_backend: str | None, backends: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if not selected_backend:
        return None
    backend = backends.get(selected_backend, {})
    if not backend.get("approval_required", False):
        return None
    return {
        "status": "approval_required",
        "backend": selected_backend,
        "reason": "paid_or_metered_media_generation",
        "default_action": "proposal_only",
        "execute_only_after_explicit_approval": True,
    }


def _pending_backends(chain: list[str], backends: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    pending = []
    for backend_id in chain:
        auth_state = str(backends.get(backend_id, {}).get("auth_state", "unknown"))
        if auth_state != "ready":
            pending.append({"backend": backend_id, "auth_state": auth_state})
    return pending


def _public_backend_contract(backend: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "capabilities",
        "modalities",
        "quality_tier",
        "cost_tier",
        "quota_policy",
        "auth_state",
        "execution_mode",
        "approval_required",
        "command_contract",
        "forbidden_command_contracts",
        "final_artifact_allowed",
    ]
    return {key: backend[key] for key in keys if key in backend}


def _intent_for_domain(mission_domain: str) -> str:
    if mission_domain.endswith("_editing"):
        return "edit"
    if mission_domain == "multimodal_asset_generation":
        return "generate_mixed_assets"
    return "generate"


def _modality_for_domain(mission_domain: str, prompt: str) -> str:
    lowered = prompt.lower()
    if mission_domain.startswith("image"):
        return "image"
    if mission_domain.startswith("video"):
        if "image to video" in lowered or "image-to-video" in lowered:
            return "image_to_video"
        if "reference video" in lowered:
            return "reference_video"
        return "video"
    return "mixed"


def _quality_target(prompt: str) -> str:
    lowered = prompt.lower()
    if any(term in lowered for term in ("commercial", "final delivery", "production", "client-ready")):
        return "commercial"
    if any(term in lowered for term in ("draft", "rough", "batch", "explore", "variations")):
        return "draft"
    if any(term in lowered for term in ("high quality", "cinematic", "polished", "hero image")):
        return "final"
    return "standard"


def _cost_policy(prompt: str) -> str:
    lowered = prompt.lower()
    if any(term in lowered for term in ("budget", "paid api ok", "auto spend", "approved budget")):
        return "budget_auto"
    if any(term in lowered for term in ("paid", "api", "commercial", "final delivery")):
        return "approval_required"
    return "free_first"


def _time_policy(prompt: str) -> str:
    lowered = prompt.lower()
    if any(term in lowered for term in ("fast", "quick", "asap", "simple")):
        return "fast"
    if any(term in lowered for term in ("async", "overnight", "batch")):
        return "async_ok"
    return "wait_for_quality"


def _policy_key(prompt: str, quality_target: str) -> str:
    lowered = prompt.lower()
    if any(term in lowered for term in ("batch", "draft", "variations", "explore")):
        return "draft_batch"
    if any(term in lowered for term in ("simple", "quick", "fast", "straight")):
        return "fast_simple"
    if quality_target == "commercial":
        return "commercial_final"
    return "high_quality_single_or_short"


def _style_constraints(prompt: str) -> list[str]:
    lowered = prompt.lower()
    constraints = []
    for marker in ("cinematic", "photorealistic", "anime", "brand style", "minimal", "editorial"):
        if marker in lowered:
            constraints.append(marker)
    return constraints


def _delivery_constraints(prompt: str) -> dict[str, Any]:
    lowered = prompt.lower()
    constraints: dict[str, Any] = {}
    for ratio in ("16:9", "9:16", "1:1", "4:5"):
        if ratio in lowered:
            constraints["aspect_ratio"] = ratio
    for platform in ("youtube", "tiktok", "instagram", "xhs", "wechat"):
        if platform in lowered:
            constraints["platform"] = platform
    return constraints


def _harness_rules(selected_backend: str | None, backends: dict[str, dict[str, Any]]) -> list[str]:
    rules = [
        "run capability/auth/quota preflight before real generation",
        "write all generated assets under runs/<task_id>/artifacts/",
        "record source, prompt, params, timestamp, backend, and cost/quota estimate",
        "do not promote final assets without QA or human acceptance",
    ]
    backend = backends.get(selected_backend or "", {})
    if selected_backend == "agy_media" or backend.get("final_artifact_allowed") is False:
        rules.append("agy_media outputs are draft candidates only and cannot be final artifacts")
    return rules
