"""Deterministic project artifact stewardship.

This module keeps task-run evidence separate from project-level deliverables.
It intentionally performs only filesystem bookkeeping: no model calls, no git
operations, and no policy decisions beyond validating the declared artifact
intent.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import fnmatch
import re
import shutil
from typing import Any

import yaml

from atomic_io import atomic_write_yaml


EVIDENCE_FILENAMES = {
    "user_request.md",
    "workflow_plan.yml",
    "state.yml",
    "progress.yml",
    "task_snapshot.yml",
    "brain_decisions.yml",
    "cost_ledger.yml",
    "01_supervisor_plan.md",
    "02_reposcout_report.md",
    "03_research_notes.md",
    "04_interface_map.md",
    "05_coder_prompt.md",
    "05_codex_prompt.md",
    "06_implementation_report.md",
    "07_validation_report.md",
    "08_audit_report.md",
    "09_archive_update.md",
    "verification_report.md",
    "self_check_report.yml",
    "sync_report.yml",
    "task_card.yml",
    "artifact_manifest.yml",
    "archive_receipt.yml",
    "artifact_lineage.yml",
    "artifact_promotion_plan.yml",
}

EVIDENCE_NAME_PATTERNS = (
    "report",
    "prompt",
    "audit",
    "validation",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _read_yaml(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if data is not None else ({} if default is None else default)
    except Exception:
        return {} if default is None else default


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _rel(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)


def _project_root(agentlab_root: Path, project: str) -> Path:
    return agentlab_root / "projects" / project


def _run_dir(agentlab_root: Path, project: str, task_id: str) -> Path:
    return _project_root(agentlab_root, project) / "runs" / task_id


def _load_workflow_plan(run_dir: Path) -> dict:
    data = _read_yaml(run_dir / "workflow_plan.yml", {})
    return data if isinstance(data, dict) else {}


def _load_content_governance(agentlab_root: Path) -> dict[str, Any]:
    data = _read_yaml(agentlab_root / "config" / "content_project_governance.yml", {})
    return data if isinstance(data, dict) else {}


def _is_active_content_project(agentlab_root: Path, project: str) -> bool:
    policy = _load_content_governance(agentlab_root)
    return project in {str(item) for item in policy.get("active_projects") or []}


def _content_governance_issues(agentlab_root: Path, project_root: Path, project: str, index: dict, run_dir: Path) -> list[str]:
    policy = _load_content_governance(agentlab_root)
    issues: list[str] = []
    forbidden_roots = {
        *[str(item) for item in policy.get("candidate_roots") or []],
        *[str(item) for item in policy.get("archive_roots") or []],
        "runs",
    }
    formal_roots = {str(item) for item in policy.get("formal_fact_roots") or ["production", "project_brain"]}
    legacy_patterns = [str(item) for item in policy.get("legacy_fact_dir_patterns") or []]

    for child in sorted(project_root.iterdir()) if project_root.exists() else []:
        if not child.is_dir():
            continue
        if any(fnmatch.fnmatch(child.name, pattern) for pattern in legacy_patterns):
            policy_path = project_root / "project_brain" / "artifact_version_policy.yml"
            if not _legacy_dir_registered(policy_path, child.name):
                issues.append(
                    f"active content project has unregistered parallel fact directory: {child.name}"
                )

    for record in index.get("artifacts") or []:
        if not isinstance(record, dict) or record.get("status") != "current":
            continue
        artifact_id = str(record.get("artifact_id") or "")
        production_path = str(record.get("production_path") or "")
        path_parts = Path(production_path).parts
        if path_parts and path_parts[0] not in formal_roots:
            issues.append(
                f"current content artifact {artifact_id} must point under production/ or project_brain/: {production_path}"
            )
        if path_parts and path_parts[0] in forbidden_roots:
            issues.append(
                f"current content artifact {artifact_id} points at non-production fact root: {production_path}"
            )
        if any(fnmatch.fnmatch(part, pattern) for part in path_parts for pattern in legacy_patterns):
            issues.append(
                f"current content artifact {artifact_id} points at legacy/candidate directory: {production_path}"
            )

    promotion_plan_exists = (run_dir / "artifact_promotion_plan.yml").exists()
    archive_claimed = _archive_completed_or_claimed(run_dir)
    if promotion_plan_exists or archive_claimed:
        required_outputs = [str(item) for item in policy.get("required_content_task_outputs") or []]
        for filename in required_outputs:
            if not (run_dir / filename).exists():
                issues.append(f"content task missing required output {filename}")
    return issues


def _legacy_dir_registered(policy_path: Path, dirname: str) -> bool:
    policy = _read_yaml(policy_path, {})
    if not isinstance(policy, dict):
        return False
    for key in ("legacy_dirs", "archive_dirs", "candidate_dirs"):
        for item in policy.get(key) or []:
            if isinstance(item, dict):
                raw = item.get("path") or item.get("dir")
            else:
                raw = item
            if Path(str(raw)).parts[:1] == (dirname,) or str(raw).rstrip("/") == dirname:
                return True
    return False


def _prompt_summary(run_dir: Path, max_chars: int = 180) -> str:
    request_path = run_dir / "user_request.md"
    if not request_path.exists():
        return ""
    for raw_line in request_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip().lstrip("#").strip()
        if not line or line.lower() in {"user request", "request"}:
            continue
        return line[:max_chars]
    return ""


def _slug_artifact_id(value: str) -> str:
    stem = Path(value).with_suffix("").as_posix()
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("_")
    return slug or "artifact"


def _is_evidence_file(path: Path | str) -> bool:
    name = Path(path).name.lower()
    if name in EVIDENCE_FILENAMES:
        return True
    stem = Path(name).stem.lower()
    return any(pattern in stem for pattern in EVIDENCE_NAME_PATTERNS)


def build_artifact_intent(
    agentlab_root: Path,
    project: str,
    task_id: str,
    project_config: dict | None = None,
) -> dict:
    """Build the task-level artifact destination contract."""
    root = _project_root(agentlab_root, project)
    run_dir = _run_dir(agentlab_root, project, task_id)
    artifact_cfg = (project_config or {}).get("artifact_steward", {})
    paths_cfg = (project_config or {}).get("paths", {})
    production_dir = Path(
        artifact_cfg.get("production_dir")
        or paths_cfg.get("artifacts")
        or root / "artifacts"
    )
    if not production_dir.is_absolute():
        production_dir = root / production_dir
    candidate_dir = Path(artifact_cfg.get("candidate_dir") or run_dir / "artifacts")
    if not candidate_dir.is_absolute():
        candidate_dir = run_dir / candidate_dir
    archive_dir = Path(artifact_cfg.get("archive_dir") or production_dir / "_archive")
    if not archive_dir.is_absolute():
        archive_dir = production_dir / archive_dir
    return {
        "version": 1,
        "project": project,
        "task_id": task_id,
        "candidate_dir": str(candidate_dir),
        "production_dir": str(production_dir),
        "archive_dir": str(archive_dir),
        "allowed_write_roots": [str(candidate_dir)],
        "declared_production_paths": list(artifact_cfg.get("declared_production_paths") or []),
        "allowed_overwrite_paths": list(artifact_cfg.get("allowed_overwrite_paths") or []),
        "forbidden_write_roots": [
            str(root / "artifacts" / "_archive"),
            str(root / "agent_docs"),
        ],
        "archive_strategy": artifact_cfg.get("archive_strategy") or "copy_existing_before_replace",
        "requires_plan_revision_for_undeclared_paths": True,
        "rules": [
            "runs/<task_id>/ contains process evidence and reports",
            "runs/<task_id>/artifacts/ contains candidate deliverables only",
            "projects/<Project>/artifacts/ contains current production deliverables only",
            "existing production files must be archived before replacement",
        ],
    }


def _artifact_intent(agentlab_root: Path, project: str, task_id: str, run_dir: Path) -> dict:
    plan = _load_workflow_plan(run_dir)
    intent = plan.get("artifact_intent")
    if isinstance(intent, dict):
        return intent
    return build_artifact_intent(agentlab_root, project, task_id)


def ensure_workflow_artifact_intent(
    agentlab_root: Path,
    project: str,
    task_id: str,
    plan_path: Path | None = None,
) -> dict:
    """Ensure workflow_plan.yml carries artifact_intent and return the plan."""
    run_dir = _run_dir(agentlab_root, project, task_id)
    plan_path = plan_path or run_dir / "workflow_plan.yml"
    plan = _read_yaml(plan_path, {})
    if not isinstance(plan, dict):
        plan = {}
    if isinstance(plan.get("artifact_intent"), dict):
        return plan
    plan["artifact_intent"] = build_artifact_intent(agentlab_root, project, task_id)
    atomic_write_yaml(plan_path, plan)
    return plan


def ensure_artifact_lineage(agentlab_root: Path, project: str, task_id: str) -> dict:
    """Create artifact_lineage.yml if the task has not written one."""
    run_dir = _run_dir(agentlab_root, project, task_id)
    path = run_dir / "artifact_lineage.yml"
    if path.exists():
        data = _read_yaml(path, {})
        return data if isinstance(data, dict) else {}
    lineage = {
        "version": 1,
        "project": project,
        "task_id": task_id,
        "created_at": _utc_now(),
        "source_prompt_summary": _prompt_summary(run_dir),
        "added": [],
        "modified": [],
        "replaced": [],
        "deprecated": [],
        "readonly_references": [],
        "evidence_only": [],
        "undeclared_paths": [],
    }
    atomic_write_yaml(path, lineage)
    return lineage


def _candidate_files(candidate_dir: Path) -> list[Path]:
    if not candidate_dir.exists():
        return []
    files = []
    for path in sorted(candidate_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(part.startswith(".") for part in path.relative_to(candidate_dir).parts):
            continue
        files.append(path)
    return files


def ensure_artifact_promotion_plan(agentlab_root: Path, project: str, task_id: str) -> dict:
    """Create artifact_promotion_plan.yml from candidate artifacts if absent."""
    run_dir = _run_dir(agentlab_root, project, task_id)
    path = run_dir / "artifact_promotion_plan.yml"
    if path.exists():
        data = _read_yaml(path, {})
        return data if isinstance(data, dict) else {}
    intent = _artifact_intent(agentlab_root, project, task_id, run_dir)
    candidate_dir = Path(intent["candidate_dir"])
    production_dir = Path(intent["production_dir"])
    promotions = []
    evidence_only = []
    for source in _candidate_files(candidate_dir):
        source_rel = _rel(source, run_dir)
        production_rel = source.relative_to(candidate_dir)
        if _is_evidence_file(source):
            evidence_only.append(source_rel)
            continue
        promotions.append(
            {
                "artifact_id": _slug_artifact_id(production_rel.as_posix()),
                "source_run_artifact": source_rel,
                "production_path": _rel(production_dir / production_rel, _project_root(agentlab_root, project)),
                "action": "promote",
                "evidence_only": False,
            }
        )
    plan = {
        "version": 1,
        "project": project,
        "task_id": task_id,
        "generated_at": _utc_now(),
        "source_prompt_summary": _prompt_summary(run_dir),
        "candidate_dir": str(candidate_dir),
        "production_dir": str(production_dir),
        "archive_dir": intent["archive_dir"],
        "promotions": promotions,
        "evidence_only": evidence_only,
    }
    atomic_write_yaml(path, plan)
    return plan


def _load_index(project_root: Path, project: str) -> dict:
    path = project_root / "project_artifact_index.yml"
    data = _read_yaml(path, {})
    if not isinstance(data, dict) or not data:
        data = {"version": 1, "project": project, "artifacts": []}
    artifacts = data.get("artifacts")
    if isinstance(artifacts, dict):
        data["artifacts"] = list(artifacts.values())
    elif not isinstance(artifacts, list):
        data["artifacts"] = []
    data.setdefault("version", 1)
    data.setdefault("project", project)
    return data


def _write_index(project_root: Path, index: dict) -> None:
    index["updated_at"] = _utc_now()
    atomic_write_yaml(project_root / "project_artifact_index.yml", index)


def _resolve_source(run_dir: Path, intent: dict, raw: str) -> tuple[Path | None, str | None]:
    if not raw:
        return None, "promotion missing source_run_artifact"
    candidate_dir = Path(intent["candidate_dir"])
    candidate = Path(raw)
    if candidate.is_absolute():
        source = candidate
    elif (run_dir / candidate).exists():
        source = run_dir / candidate
    else:
        source = candidate_dir / candidate
    if not _is_relative_to(source, candidate_dir):
        return source, f"source_run_artifact outside candidate dir: {raw}"
    if not source.exists():
        return source, f"source_run_artifact missing: {raw}"
    if _is_evidence_file(source):
        return source, f"source_run_artifact is evidence/report, not a deliverable: {raw}"
    return source, None


def _resolve_production(
    agentlab_root: Path,
    project_root: Path,
    intent: dict,
    raw: str | None,
    source: Path,
) -> tuple[Path, str | None]:
    production_dir = Path(intent["production_dir"])
    if raw:
        candidate = Path(raw)
        if candidate.is_absolute():
            target = candidate
        elif candidate.parts and candidate.parts[0] == "projects":
            target = agentlab_root / candidate
        elif candidate.parts and candidate.parts[0] == "artifacts":
            target = project_root / candidate
        else:
            target = production_dir / candidate
    else:
        target = production_dir / source.name
    if not _is_relative_to(target, production_dir):
        return target, f"production_path outside production dir: {raw or source.name}"
    if _is_evidence_file(target):
        return target, f"production_path is evidence/report, not a deliverable: {raw or source.name}"
    return target, None


def _record_index_promotion(
    index: dict,
    *,
    artifact_id: str,
    current_version: str,
    production_rel: str,
    source_task: str,
    source_prompt_summary: str,
    source_run_artifact: str,
    archive_rel: str | None,
    promoted_at: str,
) -> None:
    records = index.setdefault("artifacts", [])
    previous_current = [
        record
        for record in records
        if record.get("artifact_id") == artifact_id and record.get("status") == "current"
    ]
    previous_version = previous_current[-1].get("current_version") if previous_current else None
    if previous_version is None and archive_rel:
        previous_version = "pre_index"
    for record in previous_current:
        record["status"] = "archived"
        record["superseded_by"] = current_version
        if archive_rel:
            record["archive_path"] = archive_rel
    archived_versions = []
    if archive_rel:
        archived_versions.append(
            {
                "version": previous_version,
                "archive_path": archive_rel,
                "archived_at": promoted_at,
            }
        )
    records.append(
        {
            "artifact_id": artifact_id,
            "status": "current",
            "current_version": current_version,
            "production_path": production_rel,
            "source_task": source_task,
            "source_prompt_summary": source_prompt_summary,
            "source_run_artifact": source_run_artifact,
            "supersedes": previous_version,
            "superseded_by": None,
            "archived_versions": archived_versions,
            "evidence_only": False,
            "promoted_at": promoted_at,
        }
    )


def apply_archive_protocol(agentlab_root: Path, project: str, task_id: str) -> dict:
    """Apply artifact promotion, archive old production files, and write receipt."""
    project_root = _project_root(agentlab_root, project)
    run_dir = _run_dir(agentlab_root, project, task_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    readiness_errors = validate_content_promotion_readiness(
        agentlab_root,
        project,
        task_id,
        run_dir,
        require_archive_receipt=False,
    )
    if readiness_errors:
        receipt = {
            "version": 1,
            "project": project,
            "task_id": task_id,
            "status": "blocked",
            "created_at": _utc_now(),
            "artifact_promotion_plan": "artifact_promotion_plan.yml",
            "artifact_lineage": "artifact_lineage.yml",
            "project_artifact_index": "project_artifact_index.yml",
            "promotions_applied": [],
            "archived_paths": [],
            "errors": readiness_errors,
        }
        atomic_write_yaml(run_dir / "archive_receipt.yml", receipt)
        return receipt
    lineage = ensure_artifact_lineage(agentlab_root, project, task_id)
    plan = ensure_artifact_promotion_plan(agentlab_root, project, task_id)
    intent = _artifact_intent(agentlab_root, project, task_id, run_dir)
    archive_dir = Path(plan.get("archive_dir") or intent["archive_dir"])
    source_prompt_summary = (
        plan.get("source_prompt_summary")
        or lineage.get("source_prompt_summary")
        or _prompt_summary(run_dir)
    )
    index = _load_index(project_root, project)
    errors: list[str] = []
    promotions_applied: list[dict] = []
    archived_paths: list[str] = []
    current_stamp = _timestamp()
    promoted_at = _utc_now()

    for entry in plan.get("promotions") or []:
        if not isinstance(entry, dict):
            errors.append("promotion entry is not a mapping")
            continue
        if entry.get("evidence_only"):
            continue
        source, source_error = _resolve_source(run_dir, intent, str(entry.get("source_run_artifact") or ""))
        if source_error:
            errors.append(source_error)
            continue
        if source is None:
            errors.append("promotion source could not be resolved")
            continue
        target, target_error = _resolve_production(
            agentlab_root,
            project_root,
            intent,
            entry.get("production_path") or entry.get("target_path"),
            source,
        )
        if target_error:
            errors.append(target_error)
            continue
        artifact_id = str(entry.get("artifact_id") or _slug_artifact_id(_rel(target, Path(intent["production_dir"]))))
        current_version = f"{current_stamp}__{task_id}"
        archive_rel = None
        replaced_existing = target.exists()
        if replaced_existing:
            archive_path = archive_dir / artifact_id / f"{current_stamp}__{task_id}" / target.name
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, archive_path)
            archive_rel = _rel(archive_path, project_root)
            archived_paths.append(archive_rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        source_rel = _rel(source, run_dir)
        production_rel = _rel(target, project_root)
        _record_index_promotion(
            index,
            artifact_id=artifact_id,
            current_version=current_version,
            production_rel=production_rel,
            source_task=task_id,
            source_prompt_summary=source_prompt_summary,
            source_run_artifact=source_rel,
            archive_rel=archive_rel,
            promoted_at=promoted_at,
        )
        promotions_applied.append(
            {
                "artifact_id": artifact_id,
                "source_run_artifact": source_rel,
                "production_path": production_rel,
                "version": current_version,
                "replaced_existing": replaced_existing,
                "archive_path": archive_rel,
            }
        )

    _write_index(project_root, index)
    receipt = {
        "version": 1,
        "project": project,
        "task_id": task_id,
        "status": "failed" if errors else "completed",
        "created_at": _utc_now(),
        "artifact_promotion_plan": "artifact_promotion_plan.yml",
        "artifact_lineage": "artifact_lineage.yml",
        "project_artifact_index": "project_artifact_index.yml",
        "promotions_applied": promotions_applied,
        "archived_paths": archived_paths,
        "errors": errors,
    }
    atomic_write_yaml(run_dir / "archive_receipt.yml", receipt)
    return receipt


def validate_content_promotion_readiness(
    agentlab_root: Path,
    project: str,
    task_id: str,
    run_dir: Path | None = None,
    *,
    require_archive_receipt: bool,
) -> list[str]:
    """Return hard readiness failures for active content artifact promotion."""
    if not _is_active_content_project(agentlab_root, project):
        return []
    project_root = _project_root(agentlab_root, project)
    run_dir = run_dir or _run_dir(agentlab_root, project, task_id)
    issues: list[str] = []
    for filename in ("artifact_lineage.yml", "state_transition_proposal.yml"):
        if not (run_dir / filename).exists():
            issues.append(f"content promotion readiness missing {filename}")
    if require_archive_receipt and not (run_dir / "archive_receipt.yml").exists():
        issues.append("content promotion readiness missing archive_receipt.yml")
    index = _load_index(project_root, project) if (project_root / "project_artifact_index.yml").exists() else {"artifacts": []}
    current_by_id: dict[str, int] = {}
    for record in index.get("artifacts") or []:
        if isinstance(record, dict) and record.get("status") == "current":
            artifact_id = str(record.get("artifact_id") or "")
            current_by_id[artifact_id] = current_by_id.get(artifact_id, 0) + 1
    for artifact_id, count in current_by_id.items():
        if count > 1:
            issues.append(f"content promotion readiness failed single-current invariant for {artifact_id}")
    return issues


def _task_completed(run_dir: Path) -> bool:
    for filename in ("state.yml", "progress.yml", "task_card.yml"):
        data = _read_yaml(run_dir / filename, {})
        if isinstance(data, dict) and data.get("status") in {"complete", "completed"}:
            return True
    lifecycle = _read_yaml(run_dir / "lifecycle.yml", {})
    if isinstance(lifecycle, dict):
        final = lifecycle.get("nodes", {}).get("FINALIZE", {})
        if final.get("status") == "completed":
            return True
    return False


def _archive_completed_or_claimed(run_dir: Path) -> bool:
    lifecycle = _read_yaml(run_dir / "lifecycle.yml", {})
    if isinstance(lifecycle, dict):
        nodes = lifecycle.get("nodes", {})
        if nodes.get("ARCHIVE", {}).get("status") == "completed":
            return True
        if nodes.get("FINALIZE", {}).get("status") in {"running", "completed"}:
            return True
    return (run_dir / "09_archive_update.md").exists()


def _index_evidence_only(index: dict, production_rel: str) -> bool:
    for record in index.get("artifacts") or []:
        if not isinstance(record, dict):
            continue
        if record.get("production_path") == production_rel and (
            record.get("evidence_only") is True or record.get("status") == "evidence_only"
        ):
            return True
    return False


def _lineage_paths(lineage: dict) -> list[str]:
    paths: list[str] = []
    for section in ("added", "modified", "replaced", "deprecated", "undeclared_paths"):
        for item in lineage.get(section) or []:
            if isinstance(item, str):
                paths.append(item)
            elif isinstance(item, dict):
                for key in ("path", "production_path", "target_path"):
                    if item.get(key):
                        paths.append(str(item[key]))
    return paths


def _path_matches_declared(path_text: str, declared: list[str], project: str) -> bool:
    normalized = path_text.replace("\\", "/")
    variants = {
        normalized,
        normalized.removeprefix(f"projects/{project}/"),
    }
    for pattern in declared:
        pat = str(pattern).replace("\\", "/")
        if pat.endswith("/**"):
            prefix = pat[:-3]
            if any(value.startswith(prefix) for value in variants):
                return True
        if pat in variants:
            return True
    return False


def _looks_like_production_path(path_text: str, intent: dict, project: str) -> bool:
    path_text = path_text.replace("\\", "/")
    if path_text.startswith(f"projects/{project}/artifacts/") or path_text.startswith("artifacts/"):
        return True
    candidate = Path(path_text)
    return candidate.is_absolute() and _is_relative_to(candidate, Path(intent["production_dir"]))


def _validate_lineage_paths(intent: dict, lineage: dict, project: str) -> list[str]:
    declared = list(intent.get("declared_production_paths") or []) + list(intent.get("allowed_overwrite_paths") or [])
    issues = []
    for path_text in _lineage_paths(lineage):
        if not _looks_like_production_path(path_text, intent, project):
            continue
        if not _path_matches_declared(path_text, declared, project):
            issues.append(f"artifact_lineage declares undeclared production path: {path_text}")
    return issues


def validate_project_artifact_governance(
    agentlab_root: Path,
    project: str,
    task_id: str,
    run_dir: Path | None = None,
) -> list[str]:
    """Return fatal artifact-governance issues for a task."""
    project_root = _project_root(agentlab_root, project)
    run_dir = run_dir or _run_dir(agentlab_root, project, task_id)
    intent = _artifact_intent(agentlab_root, project, task_id, run_dir)
    production_dir = Path(intent["production_dir"])
    index_path = project_root / "project_artifact_index.yml"
    index = _load_index(project_root, project) if index_path.exists() else {"artifacts": []}
    issues: list[str] = []

    if production_dir.exists():
        for path in sorted(production_dir.rglob("*")):
            if not path.is_file():
                continue
            if "_archive" in path.relative_to(production_dir).parts:
                continue
            production_rel = _rel(path, project_root)
            if _is_evidence_file(path) and not _index_evidence_only(index, production_rel):
                issues.append(
                    "production artifact directory contains evidence/report file "
                    f"without evidence-only marker: {production_rel}"
                )

    lineage_path = run_dir / "artifact_lineage.yml"
    if lineage_path.exists():
        lineage = _read_yaml(lineage_path, {})
        if isinstance(lineage, dict):
            issues.extend(_validate_lineage_paths(intent, lineage, project))

    current_by_id: dict[str, list[dict]] = {}
    for record in index.get("artifacts") or []:
        if not isinstance(record, dict):
            continue
        if record.get("status") == "current":
            artifact_id = str(record.get("artifact_id") or "")
            current_by_id.setdefault(artifact_id, []).append(record)
            if not record.get("source_task") and not record.get("evidence_only"):
                issues.append(f"current artifact missing source_task in project_artifact_index.yml: {artifact_id}")
            if not record.get("source_run_artifact") and not record.get("evidence_only"):
                issues.append(
                    "current artifact missing source_run_artifact in "
                    f"project_artifact_index.yml: {artifact_id}"
                )
            if record.get("supersedes") and not record.get("archived_versions"):
                issues.append(f"artifact {artifact_id} supersedes an old version without archived_versions")
    for artifact_id, records in current_by_id.items():
        if len(records) > 1:
            issues.append(f"artifact {artifact_id} has multiple current versions")

    if _is_active_content_project(agentlab_root, project):
        issues.extend(_content_governance_issues(agentlab_root, project_root, project, index, run_dir))
        issues.extend(validate_content_promotion_readiness(
            agentlab_root,
            project,
            task_id,
            run_dir,
            require_archive_receipt=_task_completed(run_dir) or _archive_completed_or_claimed(run_dir),
        ))

    receipt_path = run_dir / "archive_receipt.yml"
    archive_claimed = _archive_completed_or_claimed(run_dir)
    if _task_completed(run_dir) and not receipt_path.exists():
        issues.append("completed task missing archive_receipt.yml")
    if archive_claimed:
        if not (run_dir / "artifact_lineage.yml").exists():
            issues.append("ARCHIVE completed but artifact_lineage.yml is missing")
        if not (run_dir / "artifact_promotion_plan.yml").exists():
            issues.append("ARCHIVE completed but artifact_promotion_plan.yml is missing")
        if not receipt_path.exists():
            issues.append("ARCHIVE completed but archive_receipt.yml is missing")
        if not index_path.exists():
            issues.append("ARCHIVE completed but project_artifact_index.yml is missing")

    if receipt_path.exists():
        receipt = _read_yaml(receipt_path, {})
        if isinstance(receipt, dict):
            for error in receipt.get("errors") or []:
                issues.append(f"archive_receipt error: {error}")
            for applied in receipt.get("promotions_applied") or []:
                if not isinstance(applied, dict):
                    continue
                artifact_id = applied.get("artifact_id")
                if applied.get("replaced_existing") and not applied.get("archive_path"):
                    issues.append(
                        f"artifact {artifact_id} replaced production without archive_path "
                        "in archive_receipt.yml"
                    )
                matches = [
                    record
                    for record in index.get("artifacts") or []
                    if isinstance(record, dict)
                    and record.get("artifact_id") == artifact_id
                    and record.get("status") == "current"
                    and record.get("source_task") == task_id
                    and record.get("source_run_artifact") == applied.get("source_run_artifact")
                ]
                if not matches:
                    issues.append(f"promoted artifact missing matching current ledger entry: {artifact_id}")
    return issues
