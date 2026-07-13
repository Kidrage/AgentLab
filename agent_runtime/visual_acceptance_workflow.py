"""Assemble independently owned visual evidence into promotion-gate inputs.

The ArtifactProducer, Observer, Reviewer, and Verifier each own a separate file.
This module only validates and combines those files; it cannot generate media or
promote an artifact.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any

import yaml

try:
    from agent_runtime.atomic_io import atomic_write_yaml
    from agent_runtime.visual_acceptance import evaluate_visual_candidate
except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
    from atomic_io import atomic_write_yaml
    from visual_acceptance import evaluate_visual_candidate


_PRODUCER_FILES = {
    "generation_receipt": (
        "artifacts/media_backend/generation_receipt.yml",
        "generation_receipt.yml",
    ),
    "generated_assets_manifest": (
        "artifacts/media_backend/generated_assets_manifest.yml",
        "generated_assets_manifest.yml",
    ),
    "generation_ledger": (
        "artifacts/media_backend/generation_ledger.yml",
        "generation_ledger.yml",
    ),
}
_STAGE_FILES = {
    "Observer": "visual_observation_report.yml",
    "Reviewer": "visual_review_report.yml",
    "Verifier": "visual_verification_report.yml",
}
_DIMENSIONS = ("aesthetic", "continuity", "technical", "factual_safety")


def normalize_visual_stage_report(
    content: str,
    *,
    role: str,
    provider: str,
    model: str,
    execution_id: str | None = None,
) -> dict[str, Any]:
    """Normalize provider YAML while stamping non-self-reported runtime identity."""

    raw = _yaml_mapping_from_text(content)
    candidates = raw.get("candidates") if isinstance(raw.get("candidates"), list) else []
    status = str(raw.get("status") or "").lower()
    issues: list[str] = []
    if status not in {"complete", "blocked", "not_required"}:
        issues.append("status_must_be_complete_blocked_or_not_required")
        status = "blocked"
    if not isinstance(raw.get("candidates"), list):
        issues.append("candidates_must_be_a_list")
        status = "blocked"
    identity_key = "observer" if role == "Observer" else "reviewer"
    identity = {
        "role": role,
        "id": execution_id
        or "report-sha256:"
        + hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "backend": provider,
        "model": model,
    }
    return {
        "schema_version": "visual-stage-report/v1",
        "report_type": _STAGE_FILES.get(role, f"visual_{role.lower()}_report.yml"),
        "status": status,
        "candidate_only": True,
        "production_modified": False,
        identity_key: identity,
        "candidates": candidates,
        "issues": issues + [str(item) for item in raw.get("issues", []) if str(item)],
    }


def fake_visual_stage_report(run_dir: Path, *, role: str) -> dict[str, Any]:
    """Create deterministic mock-provider evidence without claiming a live review."""

    root = Path(run_dir)
    issues: list[str] = []
    manifest, _ = _read_unique_yaml(
        root,
        _PRODUCER_FILES["generated_assets_manifest"],
        "generated_assets_manifest",
        issues,
        required=False,
    )
    assets = manifest.get("assets") if isinstance(manifest.get("assets"), list) else []
    candidates: list[dict[str, Any]] = []
    for raw_asset in assets:
        if not isinstance(raw_asset, dict):
            continue
        candidate_id = str(raw_asset.get("candidate_id") or "").strip()
        if not candidate_id:
            continue
        if role == "Observer":
            asset = {
                key: raw_asset.get(key)
                for key in ("path", "sha256", "size_bytes")
            }
            row: dict[str, Any] = {
                "candidate_id": candidate_id,
                "status": "complete",
                "asset": asset,
                "observations": ["deterministic mock-provider fixture inspected the declared asset"],
            }
            locator = _fixture_locator(str(raw_asset.get("media_type") or ""), raw_asset)
            row.update(locator)
        elif role == "Reviewer":
            row = {
                "candidate_id": candidate_id,
                "status": "complete",
                "asset": {
                    key: raw_asset.get(key)
                    for key in ("path", "sha256", "size_bytes")
                },
                "dimensions": {
                    dimension: {
                        "verdict": "pass",
                        "evidence": [
                            f"{role} deterministic mock-provider fixture checked {dimension}"
                        ],
                    }
                    for dimension in _DIMENSIONS
                },
            }
        else:
            row = {
                "candidate_id": candidate_id,
                "status": "complete",
                "asset": {
                    key: raw_asset.get(key)
                    for key in ("path", "sha256", "size_bytes")
                },
                "checks": {
                    check: {
                        "verdict": "pass",
                        "evidence": [
                            f"Verifier deterministic mock-provider fixture checked {check}"
                        ],
                    }
                    for check in (
                        "asset_integrity",
                        "evidence_chain",
                        "reviewer_independence",
                        "promotion_boundary",
                    )
                },
            }
        candidates.append(row)

    identity_key = "observer" if role == "Observer" else "reviewer"
    return {
        "schema_version": "visual-stage-report/v1",
        "report_type": _STAGE_FILES[role],
        "status": "complete" if candidates else "not_required",
        "candidate_only": True,
        "production_modified": False,
        identity_key: {
            "role": role,
            "id": f"fake-provider-{role.lower()}",
            "backend": "fake_provider",
            "model": f"deterministic_{role.lower()}_fixture",
        },
        "candidates": candidates,
        "issues": issues,
    }


def visual_stage_report_issues(report: dict[str, Any], *, role: str) -> list[str]:
    issues = [str(item) for item in report.get("issues", []) if str(item)]
    if report.get("status") == "blocked":
        issues.append(f"{role} visual stage returned blocked")
    identity_key = "observer" if role == "Observer" else "reviewer"
    identity = report.get(identity_key)
    if not isinstance(identity, dict) or identity.get("role") != role:
        issues.append(f"{role} runtime identity is missing")
    return list(dict.fromkeys(issues))


def write_media_qc_report(run_dir: Path, review_report: dict[str, Any]) -> Path:
    """Materialize Reviewer-owned QC evidence without producer participation."""

    path = Path(run_dir) / "media_qc_report.yml"
    atomic_write_yaml(
        path,
        {
            "schema_version": "media-qc-report/v1",
            "status": review_report.get("status"),
            "candidate_only": True,
            "production_modified": False,
            "owner": review_report.get("reviewer"),
            "candidates": review_report.get("candidates", []),
            "source_report": "visual_review_report.yml",
            "self_approved": False,
        },
    )
    return path


def materialize_visual_acceptance(run_dir: Path, *, task_id: str) -> dict[str, Any]:
    """Build and evaluate visual candidates from role-owned evidence files.

    Missing or ambiguous evidence blocks the workflow. A dry run whose generation
    ledger proves that no asset was produced is explicitly ``not_required``.
    """

    root = Path(run_dir).resolve(strict=False)
    issues: list[str] = []
    ledger, ledger_path = _read_unique_yaml(
        root, _PRODUCER_FILES["generation_ledger"], "generation_ledger", issues,
        required=False,
    )
    manifest, manifest_path = _read_unique_yaml(
        root,
        _PRODUCER_FILES["generated_assets_manifest"],
        "generated_assets_manifest",
        issues,
        required=False,
    )

    if not manifest:
        if not issues and _proves_no_live_asset_was_required(ledger, manifest):
            return _write_workflow_decision(
                root,
                task_id=task_id,
                status="not_required",
                decisions=[],
                issues=issues,
                candidate_count=0,
            )
        issues.append("missing:generated_assets_manifest.yml")
        return _write_workflow_decision(
            root,
            task_id=task_id,
            status="blocked",
            decisions=[],
            issues=issues,
            candidate_count=0,
        )

    assets = manifest.get("assets")
    if isinstance(assets, list) and not assets:
        if not issues and _proves_no_live_asset_was_required(ledger, manifest):
            return _write_workflow_decision(
                root,
                task_id=task_id,
                status="not_required",
                decisions=[],
                issues=issues,
                candidate_count=0,
            )
    if not isinstance(assets, list) or not assets:
        issues.append("invalid:generated_assets_manifest.assets")

    generation_receipt, generation_receipt_path = _read_unique_yaml(
        root,
        _PRODUCER_FILES["generation_receipt"],
        "generation_receipt",
        issues,
        required=True,
    )

    stage_reports: dict[str, dict[str, Any]] = {}
    stage_paths: dict[str, Path] = {}
    for role, filename in _STAGE_FILES.items():
        report, path = _read_unique_yaml(
            root, (filename,), Path(filename).stem, issues, required=True,
        )
        if report:
            stage_reports[role] = report
        if path:
            stage_paths[role] = path

    if issues:
        return _write_workflow_decision(
            root,
            task_id=task_id,
            status="blocked",
            decisions=[],
            issues=issues,
            candidate_count=len(assets) if isinstance(assets, list) else 0,
        )

    for role, report in stage_reports.items():
        if str(report.get("status") or "").lower() != "complete":
            issues.append(f"non_terminal:{_STAGE_FILES[role]}")
        identity_key = "observer" if role == "Observer" else "reviewer"
        identity = report.get(identity_key)
        if not isinstance(identity, dict) or identity.get("role") != role:
            issues.append(f"role_owner_mismatch:{_STAGE_FILES[role]}:{role}")

    asset_rows = _index_rows(assets, "generated_assets_manifest", issues)
    stage_rows = {
        role: _index_rows(report.get("candidates"), filename, issues)
        for role, report in stage_reports.items()
        for filename in (_STAGE_FILES[role],)
    }
    expected_ids = set(asset_rows)
    for role, rows in stage_rows.items():
        missing = sorted(expected_ids - set(rows))
        extra = sorted(set(rows) - expected_ids)
        issues.extend(f"missing_candidate:{_STAGE_FILES[role]}:{item}" for item in missing)
        issues.extend(f"unknown_candidate:{_STAGE_FILES[role]}:{item}" for item in extra)

    if issues:
        return _write_workflow_decision(
            root,
            task_id=task_id,
            status="blocked",
            decisions=[],
            issues=issues,
            candidate_count=len(asset_rows),
        )

    evidence_receipts = {
        "generation_receipt": _file_receipt(root, generation_receipt_path),
        "generated_assets_manifest": _file_receipt(root, manifest_path),
        **{
            role.lower(): _file_receipt(root, path)
            for role, path in stage_paths.items()
        },
    }
    candidates: list[dict[str, Any]] = []
    for candidate_id in sorted(asset_rows):
        asset = dict(asset_rows[candidate_id])
        asset.pop("candidate_id", None)
        observation = dict(stage_rows["Observer"][candidate_id])
        observation.pop("candidate_id", None)
        observation["observer"] = dict(stage_reports["Observer"]["observer"])

        reviews: list[dict[str, Any]] = []
        for role in ("Reviewer", "Verifier"):
            review = dict(stage_rows[role][candidate_id])
            review.pop("candidate_id", None)
            review["reviewer"] = dict(stage_reports[role]["reviewer"])
            reviews.append(review)

        candidates.append(
            {
                "candidate_id": candidate_id,
                "candidate_only": True,
                "status": "complete",
                "asset": asset,
                "generation_receipt": dict(generation_receipt),
                "observer_evidence": observation,
                "reviews": reviews,
                "evidence_receipts": evidence_receipts,
            }
        )

    decisions = [
        evaluate_visual_candidate(candidate, workspace=root)
        for candidate in candidates
    ]
    for decision in decisions:
        for reason in decision.get("blocking_reasons") or []:
            if isinstance(reason, dict):
                issues.append(
                    "acceptance:"
                    + str(decision.get("candidate_id") or "<missing>")
                    + ":"
                    + str(reason.get("code") or "unknown")
                )

    manifest_payload = {
        "schema_version": "visual-acceptance-candidates/v1",
        "task_id": task_id,
        "candidate_only": True,
        "production_modified": False,
        "candidates": candidates,
    }
    atomic_write_yaml(root / "visual_acceptance_candidate.yml", manifest_payload)
    return _write_workflow_decision(
        root,
        task_id=task_id,
        status="pass" if not issues else "blocked",
        decisions=decisions,
        issues=issues,
        candidate_count=len(candidates),
    )


def _proves_no_live_asset_was_required(
    ledger: dict[str, Any],
    manifest: dict[str, Any],
) -> bool:
    """Accept no-asset only for an explicit non-live dry/mock execution."""

    if not isinstance(ledger, dict) or ledger.get("live") is not False:
        return False
    if str(ledger.get("status") or "") not in {"dry_run", "not_required"}:
        return False
    generated_assets = ledger.get("generated_assets")
    if not isinstance(generated_assets, list) or generated_assets:
        return False
    if manifest:
        return (
            manifest.get("status") == "not_required"
            and manifest.get("assets") == []
        )
    return True


def _read_unique_yaml(
    root: Path,
    relative_paths: tuple[str, ...],
    label: str,
    issues: list[str],
    *,
    required: bool,
) -> tuple[dict[str, Any], Path | None]:
    existing = [root / rel for rel in relative_paths if (root / rel).is_file()]
    if not existing:
        if required:
            issues.append(f"missing:{relative_paths[0]}")
        return {}, None
    if len(existing) > 1:
        payloads = [path.read_bytes() for path in existing]
        if any(payload != payloads[0] for payload in payloads[1:]):
            issues.append(f"ambiguous:{label}")
            return {}, None
    path = existing[0]
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        issues.append(f"invalid_yaml:{path.relative_to(root).as_posix()}")
        return {}, path
    if not isinstance(payload, dict):
        issues.append(f"invalid_mapping:{path.relative_to(root).as_posix()}")
        return {}, path
    return payload, path


def _index_rows(raw_rows: Any, label: str, issues: list[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_rows, list):
        issues.append(f"invalid_candidates:{label}")
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(raw_rows):
        if not isinstance(row, dict):
            issues.append(f"invalid_candidate:{label}:{index}")
            continue
        candidate_id = str(row.get("candidate_id") or "").strip()
        if not candidate_id:
            issues.append(f"missing_candidate_id:{label}:{index}")
            continue
        if candidate_id in indexed:
            issues.append(f"duplicate_candidate_id:{label}:{candidate_id}")
            continue
        indexed[candidate_id] = row
    return indexed


def _file_receipt(root: Path, path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": None, "sha256": None, "size_bytes": None}
    payload = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }


def _write_workflow_decision(
    root: Path,
    *,
    task_id: str,
    status: str,
    decisions: list[dict[str, Any]],
    issues: list[str],
    candidate_count: int,
) -> dict[str, Any]:
    if status == "not_required":
        atomic_write_yaml(
            root / "visual_acceptance_candidate.yml",
            {
                "schema_version": "visual-acceptance-candidates/v1",
                "task_id": task_id,
                "status": "not_required",
                "candidate_only": True,
                "production_modified": False,
                "candidates": [],
            },
        )
    result = {
        "schema_version": "visual-acceptance-workflow/v1",
        "task_id": task_id,
        "status": status,
        "candidate_only": True,
        "production_modified": False,
        "promotion_performed": False,
        "candidate_count": candidate_count,
        "decisions": decisions,
        "issues": list(dict.fromkeys(issues)),
    }
    atomic_write_yaml(root / "visual_acceptance_decision.yml", result)
    return result


def _yaml_mapping_from_text(content: str) -> dict[str, Any]:
    candidates = [content]
    wrapped_output = re.search(
        r"(?:^|\n)## Output\s*\n+(.*?)(?=\n## stderr\s*\n|\Z)",
        content,
        flags=re.DOTALL,
    )
    if wrapped_output:
        candidates.append(wrapped_output.group(1).strip())
    candidates.extend(
        match.group(1)
        for match in re.finditer(
            r"```(?:ya?ml)?\s*\n(.*?)```",
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )
    for candidate in candidates:
        try:
            parsed = yaml.safe_load(candidate) or {}
        except yaml.YAMLError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _fixture_locator(media_type: str, asset: dict[str, Any]) -> dict[str, Any]:
    digest = asset.get("sha256")
    if media_type == "video":
        return {
            "keyframes": [{"timestamp_seconds": 0, "sha256": digest}],
            "timestamps": [{"start_seconds": 0, "end_seconds": 1}],
        }
    if media_type == "audio":
        return {"timestamps": [{"start_seconds": 0, "end_seconds": 1}]}
    if media_type == "pdf":
        return {"pages": [{"page": 1, "sha256": digest}]}
    return {"keyframes": [{"label": "full_frame", "sha256": digest}]}
