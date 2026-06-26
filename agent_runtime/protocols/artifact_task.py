"""Artifact Producer task contracts and capability routing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


ARTIFACT_PRODUCER_ROLE = "ArtifactProducer"

ARTIFACT_TYPE_HINTS: dict[str, tuple[str, ...]] = {
    "image": (
        "image",
        "picture",
        "photo",
        "png",
        "jpg",
        "jpeg",
        "poster",
        "generate image",
        "生成图片",
        "图片",
        "图像",
        "海报",
        "插画",
        "配图",
    ),
    "video": ("video", "mp4", "movie", "视频", "影片", "短片"),
    "audio": ("audio", "voice", "speech", "mp3", "wav", "音频", "语音", "配音"),
    "spreadsheet": ("spreadsheet", "xlsx", "excel", "csv", "sheet", "表格", "电子表格"),
    "presentation": ("presentation", "slides", "slide deck", "ppt", "pptx", "幻灯片", "演示文稿"),
    "text": (
        "article",
        "report",
        "document",
        "markdown",
        "memo",
        "prd",
        "write a",
        "draft",
        "文本",
        "文档",
        "报告",
        "文章",
        "方案",
        "交接",
    ),
}

DEFAULT_FORMAT_BY_TYPE = {
    "audio": "wav",
    "image": "png",
    "mixed": "directory",
    "presentation": "pptx",
    "spreadsheet": "xlsx",
    "text": "markdown",
    "video": "mp4",
}

DEFAULT_CAPABILITY_BY_TYPE = {
    "audio": ["generate_audio", "write_artifact_file"],
    "image": ["generate_image", "write_artifact_file"],
    "mixed": ["produce_mixed_artifacts", "write_artifact_file", "validate_artifact_contract"],
    "presentation": ["create_presentation", "write_artifact_file"],
    "spreadsheet": ["create_spreadsheet", "write_artifact_file"],
    "text": ["write_text_artifact", "write_artifact_file"],
    "video": ["generate_video", "write_artifact_file"],
}


@dataclass(frozen=True)
class ArtifactRoute:
    provider_id: str
    worker: str
    priority: int
    fallback: bool
    reason: str


def _read_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or default
    except Exception:
        return default


def _load_policy(root: Path) -> dict[str, Any]:
    return _read_yaml(Path(root) / "config" / "artifact_task_policy.yml", {}) or {}


def infer_artifact_type(task_text: str) -> str | None:
    """Infer the non-code artifact type requested by text, if any."""
    lowered = str(task_text or "").lower()
    matched: list[str] = []
    for artifact_type, hints in ARTIFACT_TYPE_HINTS.items():
        if any(hint.lower() in lowered for hint in hints):
            matched.append(artifact_type)
    if len(matched) > 1:
        return "mixed"
    return matched[0] if matched else None


def capabilities_for_artifact_type(root: Path, artifact_type: str) -> list[str]:
    policy = _load_policy(root)
    configured = ((policy.get("artifact_types") or {}).get(artifact_type) or {}).get("required_capabilities")
    return list(configured or DEFAULT_CAPABILITY_BY_TYPE.get(artifact_type, []))


def route_artifact_provider(
    root: Path,
    artifact_type: str,
    *,
    required_capabilities: list[str] | None = None,
    preferred_provider: str | None = None,
) -> dict[str, Any]:
    """Select the highest priority provider that can produce an artifact type."""
    policy = _load_policy(root)
    providers = policy.get("providers") or {}
    required = set(required_capabilities or capabilities_for_artifact_type(root, artifact_type))
    candidates: list[ArtifactRoute] = []

    for provider_id, cfg in providers.items():
        handles = set(cfg.get("handles") or [])
        capabilities = set(cfg.get("capabilities") or [])
        if artifact_type not in handles and "mixed" not in handles:
            continue
        if not required.issubset(capabilities):
            continue
        priority = int(cfg.get("priority", 0))
        if preferred_provider and provider_id == preferred_provider:
            priority += 1000
        candidates.append(ArtifactRoute(
            provider_id=provider_id,
            worker=str(cfg.get("worker", "")),
            priority=priority,
            fallback=bool(cfg.get("fallback", False)),
            reason=f"{provider_id} handles {artifact_type} with required capabilities",
        ))

    if not candidates:
        fallback = [
            ArtifactRoute(
                provider_id=provider_id,
                worker=str(cfg.get("worker", "")),
                priority=int(cfg.get("priority", 0)),
                fallback=bool(cfg.get("fallback", False)),
                reason=f"{provider_id} is fallback for artifact production",
            )
            for provider_id, cfg in providers.items()
            if cfg.get("fallback")
        ]
        candidates = fallback

    candidates.sort(key=lambda item: item.priority, reverse=True)
    selected = candidates[0] if candidates else None
    return {
        "artifact_type": artifact_type,
        "required_capabilities": sorted(required),
        "selected": asdict(selected) if selected else None,
        "candidates": [asdict(item) for item in candidates],
        "status": "routed" if selected else "capability_mismatch",
    }


def build_artifact_task_contract(
    root: Path,
    task_text: str,
    *,
    artifact_type: str | None = None,
    output_path: str | None = None,
    project: str = "AgentLab",
    task_id: str = "task_0001",
    preferred_provider: str | None = None,
) -> dict[str, Any]:
    resolved_type = artifact_type or infer_artifact_type(task_text) or "text"
    output_format = DEFAULT_FORMAT_BY_TYPE.get(resolved_type, "artifact")
    path = output_path or f"projects/{project}/runs/{task_id}/outputs/{resolved_type}.{output_format}"
    required_capabilities = capabilities_for_artifact_type(root, resolved_type)
    route = route_artifact_provider(
        root,
        resolved_type,
        required_capabilities=required_capabilities,
        preferred_provider=preferred_provider,
    )
    return {
        "packet_type": "agentlab_artifact_task",
        "schema_version": 1,
        "role": ARTIFACT_PRODUCER_ROLE,
        "project": project,
        "task_id": task_id,
        "intent": "create",
        "artifact_type": resolved_type,
        "required_capabilities": required_capabilities,
        "output": {
            "path": path,
            "format": output_format,
        },
        "requirements": [
            {"kind": "user_request", "text": task_text},
        ],
        "validation": {
            "mode": "file_exists",
            "required_paths": [path],
        },
        "routing": route,
        "fallback": {
            "allowed": True,
            "status_on_missing_capability": "capability_mismatch",
        },
    }


def load_artifact_task_for_run(root: Path, project: str, task_id: str) -> dict[str, Any] | None:
    path = Path(root) / "projects" / project / "runs" / task_id / "artifact_task.yml"
    data = _read_yaml(path)
    return data if isinstance(data, dict) else None


def run_artifact_task_doctor(root: Path) -> dict[str, Any]:
    from agent_runtime.protocols.enforcement import check_role_binding

    root = Path(root)
    policy = _load_policy(root)
    checks: list[dict[str, str]] = []

    def check(ok: bool, check_id: str, message: str) -> None:
        checks.append({
            "id": check_id,
            "status": "pass" if ok else "fail",
            "severity": "fail",
            "message": message,
        })

    check(bool(policy), "artifact_task_policy_present", "config/artifact_task_policy.yml is present")
    check((root / "docs" / "ARTIFACT_PRODUCER_PROTOCOL.md").exists(), "artifact_protocol_doc_present", "Artifact Producer protocol doc exists")

    artifact_types = policy.get("artifact_types") or {}
    for required in ("text", "image", "video", "audio", "spreadsheet", "presentation", "mixed"):
        cfg = artifact_types.get(required) or {}
        check(bool(cfg.get("required_capabilities")), "artifact_type_capabilities_present", f"{required} has required capabilities")

    providers = policy.get("providers") or {}
    for provider_id in ("codex_high_cli", "agy_cli", "qwen_37max_api"):
        cfg = providers.get(provider_id) or {}
        check(bool(cfg), "artifact_provider_present", f"{provider_id} provider is configured")
        check(bool(cfg.get("worker")), "artifact_provider_worker_present", f"{provider_id} has a worker binding")
        if cfg.get("worker"):
            allowed, reason = check_role_binding(root, str(cfg["worker"]), ARTIFACT_PRODUCER_ROLE)
            check(allowed, "artifact_provider_worker_bound", f"{provider_id}/{cfg['worker']}: {reason}")

    sample = build_artifact_task_contract(root, "Generate an image and spreadsheet bundle.", artifact_type="mixed")
    check(sample["routing"]["status"] == "routed", "artifact_router_routes_sample", "artifact router can route a mixed sample task")
    check(sample["packet_type"] == "agentlab_artifact_task", "artifact_task_contract_generates", "artifact task contract generation works")

    failed = [item for item in checks if item["status"] != "pass" and item["severity"] == "fail"]
    return {
        "doctor": "artifact_task_doctor",
        "status": "pass" if not failed else "fail",
        "summary": {"checks": len(checks), "failed": len(failed)},
        "checks": checks,
    }
