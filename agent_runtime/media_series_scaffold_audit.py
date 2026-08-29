"""Local audit for media-series scaffold candidate runs.

The media scaffold run may contain legacy task-shell files from earlier
initialization templates. This audit intentionally evaluates the active route,
production pack, media contracts, and candidate artifacts instead of treating
old placeholder files as active production evidence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

try:
    from agent_runtime.report_sanitizer import write_report_yaml
    from agent_runtime.run_retention import resolve_run_dir
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from report_sanitizer import write_report_yaml
    from run_retention import resolve_run_dir


DEFAULT_MEDIA_SERIES_RUN = "task_probe_crown_comic_video_poster_series_scaffold_20260707"
PROJECT = "Crown_of_Ash"
PACK_ID = "media_series_production"
ROUTE_KEY = "media_generation_task"

REQUIRED_MEDIA_ARTIFACTS = [
    "episode_plan.yml",
    "shot_list.yml",
    "character_visual_bible.yml",
    "asset_registry.yml",
    "prompt_pack.yml",
    "generation_ledger.yml",
    "media_continuity_ledger.yml",
    "media_qc_report.yml",
    "narrative_media_delivery_receipt.yml",
    "media_generation_contract.yml",
]

REQUIRED_AGENTS = {"Supervisor", "ArtifactProducer", "TesterAuditor", "Verifier"}
FORBIDDEN_ACTIVE_AGENTS = {"RepoScout", "InterfaceMapper", "Coder", "PromptEngineer"}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _yaml_file_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "status": "missing"}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return {"path": str(path), "status": "invalid_yaml", "error": str(exc)}
    if not isinstance(data, dict):
        return {"path": str(path), "status": "invalid_shape"}
    return {"path": str(path), "status": "pass", "keys": sorted(str(key) for key in data.keys())}


def _media_production_files(project_root: Path) -> list[str]:
    artifacts_root = project_root / "production" / "media"
    if not artifacts_root.exists():
        return []
    return [
        str(path.relative_to(project_root))
        for path in sorted(artifacts_root.rglob("*"))
        if path.is_file() and path.name != ".gitkeep"
    ]


def _artifact_scope_ok(data: dict[str, Any], name: str) -> bool:
    if name == "media_generation_contract.yml":
        blocker = data.get("execution_blocker")
        legacy_missing_key = (
            data.get("contract_type") == "media_generation_contract"
            and data.get("selected_backend") == "grok_direct"
            and data.get("executable") is False
            and isinstance(blocker, dict)
            and blocker.get("status") == "missing_auth"
        )
        oauth_handoff = (
            data.get("contract_type") == "media_generation_contract"
            and data.get("selected_backend") == "hermes_grok_oauth"
            and data.get("executable") is True
            and blocker is None
            and data.get("backend_contracts", {}).get("hermes_grok_oauth", {}).get("adapter_kind")
            in {"local_grok_cli", "grok_cli_oauth"}
            and data.get("backend_contracts", {}).get("hermes_grok_oauth", {}).get("final_artifact_allowed") is False
        )
        return legacy_missing_key or oauth_handoff
    return (
        data.get("production_pack") == PACK_ID
        and data.get("status") == "candidate"
        and data.get("candidate_only") is True
        and data.get("production_modified") is False
    )


def build_media_series_scaffold_audit(
    root: Path,
    *,
    task_id: str = DEFAULT_MEDIA_SERIES_RUN,
) -> dict[str, Any]:
    """Build an evidence-only audit for the Crown media scaffold run."""
    root = root.resolve()
    project_root = root / "projects" / PROJECT
    run_dir = resolve_run_dir(root, PROJECT, task_id)
    if not run_dir.is_dir():
        return {
            "schema_version": 1,
            "report_type": "agentlab_media_series_scaffold_audit",
            "root": str(root),
            "project": PROJECT,
            "task_id": task_id,
            "run_dir": str(run_dir),
            "status": "retired",
            "checks": [
                {
                    "id": "legacy_scaffold_retired",
                    "status": "pass",
                    "summary": (
                        "The legacy media scaffold is not an active project task; "
                        "its removed runtime cannot be used as current production evidence."
                    ),
                }
            ],
            "evidence": [],
            "summary": {
                "live_generation": False,
                "active_candidate_available": False,
            },
            "issues": [],
            "notes": [
                "Create a new ArtifactProducer task to establish fresh media candidate evidence.",
            ],
        }
    workflow = _read_yaml(run_dir / "workflow_plan.yml")
    manifest = _read_yaml(run_dir / "artifact_manifest.yml")
    receipt = _read_yaml(run_dir / "narrative_media_delivery_receipt.yml")
    current_preflight = root / "acceptance_runs" / "agentlab_capability_acceptance" / "grok_media_preflight_current.yml"
    backend_preflight = run_dir / "artifacts" / "media_backend" / "media_backend_preflight.yml"
    live_smoke_preflight = run_dir / "artifacts" / "media_backend_live_smoke_20260707" / "media_backend_preflight.yml"
    preflight = _read_yaml(current_preflight) or _read_yaml(live_smoke_preflight) or _read_yaml(backend_preflight)

    active_agents = set(workflow.get("route", {}).get("agents") or [])
    pack = workflow.get("production_pack", {}) if isinstance(workflow.get("production_pack"), dict) else {}
    artifact_statuses = [_yaml_file_status(run_dir / name) for name in REQUIRED_MEDIA_ARTIFACTS]
    artifact_data = {name: _read_yaml(run_dir / name) for name in REQUIRED_MEDIA_ARTIFACTS}
    scope_failures = [
        name
        for name, data in artifact_data.items()
        if not data or not _artifact_scope_ok(data, name)
    ]
    missing_backend_files = [
        str(path)
        for path in [
            backend_preflight,
            run_dir / "artifacts" / "media_backend" / "media_backend_payload_plan.yml",
            run_dir / "artifacts" / "media_backend" / "generation_ledger.yml",
            live_smoke_preflight,
            run_dir / "artifacts" / "media_backend_live_smoke_20260707" / "media_backend_payload_plan.yml",
            run_dir / "artifacts" / "media_backend_live_smoke_20260707" / "generation_ledger.yml",
        ]
        if not path.exists()
    ]
    auth_check = next((check for check in preflight.get("checks", []) if check.get("id") == "auth_secret_present"), {})
    local_cli_check = next(
        (
            check
            for check in preflight.get("checks", [])
            if check.get("id") in {"local_cli_available", "oauth_cli_available"}
        ),
        {},
    )
    accepted_env = auth_check.get("accepted_env") or [
        preflight.get("api_key_env"),
        *(preflight.get("backend", {}).get("api_key_env_aliases") or []),
    ]
    backend_preflight_ok = (
        preflight.get("status") == "ready"
        and preflight.get("backend_id") == "hermes_grok_oauth"
        and preflight.get("adapter_kind") in {"local_grok_cli", "grok_cli_oauth"}
        and local_cli_check.get("status") == "pass"
    )
    legacy_backend_block_ok = (
        preflight.get("status") == "blocked"
        and preflight.get("block_reason") == "missing_auth"
        and preflight.get("backend_id") == "grok_direct"
        and "XAI_API_KEY" in [str(item) for item in accepted_env if item]
        and "GROK_API_KEY" in [str(item) for item in accepted_env if item]
    )

    backend_preflight_check = {
        "id": "backend_preflight_is_safe_and_explainable",
        "status": "pass"
        if backend_preflight_ok or legacy_backend_block_ok
        else "fail",
        "preflight_status": preflight.get("status"),
        "backend_id": preflight.get("backend_id"),
        "adapter_kind": preflight.get("adapter_kind"),
        "local_cli_available": local_cli_check.get("status"),
        "accepted_env": [str(item) for item in accepted_env if item],
    }
    if preflight.get("block_reason"):
        backend_preflight_check["block_reason"] = preflight.get("block_reason")

    checks = [
        {
            "id": "active_route_uses_media_pack",
            "status": "pass"
            if workflow.get("route", {}).get("route_key") == ROUTE_KEY
            and pack.get("pack_id") == PACK_ID
            and pack.get("route_key") == ROUTE_KEY
            else "fail",
            "route_key": workflow.get("route", {}).get("route_key"),
            "pack_id": pack.get("pack_id"),
        },
        {
            "id": "active_agents_are_media_chain",
            "status": "pass"
            if REQUIRED_AGENTS.issubset(active_agents) and not (FORBIDDEN_ACTIVE_AGENTS & active_agents)
            else "fail",
            "agents": sorted(active_agents),
            "missing_required_agents": sorted(REQUIRED_AGENTS - active_agents),
            "forbidden_active_agents": sorted(FORBIDDEN_ACTIVE_AGENTS & active_agents),
        },
        {
            "id": "artifact_manifest_passes",
            "status": "pass"
            if manifest.get("valid") is True
            and manifest.get("pass_rate") == 1.0
            and not manifest.get("issues")
            else "fail",
            "manifest": manifest,
        },
        {
            "id": "required_media_artifacts_are_valid_yaml",
            "status": "pass" if all(item.get("status") == "pass" for item in artifact_statuses) else "fail",
            "files": artifact_statuses,
        },
        {
            "id": "media_artifacts_are_candidate_only",
            "status": "pass" if not scope_failures else "fail",
            "scope_failures": scope_failures,
        },
        {
            "id": "delivery_receipt_blocks_promotion",
            "status": "pass"
            if receipt.get("status") == "candidate"
            and receipt.get("candidate_only") is True
            and receipt.get("production_modified") is False
            and receipt.get("acceptance_required_before_promotion") is True
            else "fail",
            "receipt_status": receipt.get("status"),
            "candidate_only": receipt.get("candidate_only"),
            "production_modified": receipt.get("production_modified"),
        },
        backend_preflight_check,
        {
            "id": "backend_dry_run_ledgers_exist",
            "status": "pass" if not missing_backend_files else "fail",
            "missing": missing_backend_files,
        },
        {
            "id": "project_media_production_not_modified",
            "status": "pass" if not _media_production_files(project_root) else "fail",
            "production_media_files": _media_production_files(project_root),
        },
    ]
    issues = [check for check in checks if check.get("status") != "pass"]
    evidence = [
        str(run_dir / "workflow_plan.yml"),
        str(run_dir / "artifact_manifest.yml"),
        *[str(run_dir / name) for name in REQUIRED_MEDIA_ARTIFACTS],
        str(current_preflight),
        str(backend_preflight),
        str(live_smoke_preflight),
    ]
    summary = {
        "route_key": workflow.get("route", {}).get("route_key"),
        "pack_id": pack.get("pack_id"),
        "required_media_artifacts": len(REQUIRED_MEDIA_ARTIFACTS),
        "manifest_pass_rate": manifest.get("pass_rate"),
        "live_generation": False,
        "backend_status": preflight.get("status"),
        "candidate_only": receipt.get("candidate_only") is True,
        "production_modified": receipt.get("production_modified") is True,
    }
    if preflight.get("block_reason"):
        summary["backend_block_reason"] = preflight.get("block_reason")

    return {
        "schema_version": 1,
        "report_type": "agentlab_media_series_scaffold_audit",
        "root": str(root),
        "project": PROJECT,
        "task_id": task_id,
        "run_dir": str(run_dir),
        "status": "pass" if not issues else "fail",
        "checks": checks,
        "evidence": evidence,
        "summary": summary,
        "issues": issues,
    }


def write_media_series_scaffold_audit(
    root: Path,
    out: Path,
    *,
    task_id: str = DEFAULT_MEDIA_SERIES_RUN,
) -> dict[str, Any]:
    report = build_media_series_scaffold_audit(root, task_id=task_id)
    write_report_yaml(out, report, root)
    return report
