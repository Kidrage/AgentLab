"""Local audit for Crown of Ash live narrative candidate runs."""

from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
import re
from typing import Any

import yaml

try:
    from agent_runtime.report_sanitizer import write_report_yaml
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from report_sanitizer import write_report_yaml

try:
    from narrative_delivery import validate_narrative_delivery
except ImportError:  # pragma: no cover - package import path
    from agent_runtime.narrative_delivery import validate_narrative_delivery

try:
    from narrative_repetition import (
        repetition_evidence_from_paragraphs,
        substantive_paragraphs,
    )
except ImportError:  # pragma: no cover - package import path
    from agent_runtime.narrative_repetition import (
        repetition_evidence_from_paragraphs,
        substantive_paragraphs,
    )


DEFAULT_CROWN_LIVE_RUN = "task_narrative_eval_ch01_live_ch01_20260707_cli_fallback"
BATCH_REQUIRED_FILES = (
    "chapter_packet.yml",
    "fiction_draft.md",
    "continuity_ledger.yml",
    "state_transition_proposal.yml",
    "narrative_delivery_receipt.yml",
    "writer_output_contract.yml",
)
BATCH_LEDGER_LISTS = (
    "plot_state_changes",
    "character_changes",
    "relationship_or_worldline_changes",
    "foreshadowing",
)
BATCH_RECEIPT_CHECKS = (
    "chapter_and_title",
    "required_beats",
    "continuity_outputs",
    "production_untouched",
    "deprecated_sources_excluded",
)
AGY_HIGH_MODEL_LABEL = "Gemini 3.5 Flash (High)"
_V2_CANDIDATE_JOB_MODES = frozenset(
    {
        ("narrative_generation", "generate_candidate"),
        ("narrative_revision", "targeted_rewrite"),
    }
)
_V2_REVISION_IDENTITY_FIELDS = (
    "candidate_set_id",
    "source_job_id",
    "source_run_id",
    "triggered_by_audit_id",
    "attempt_id",
    "lease_token",
    "lease_expires_at",
    "fencing_token",
)
_V2_REVISION_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _root_snapshot_bytes(root: Path, path: Path) -> bytes | None:
    from agent_runtime.narrative.production.live_writer_preflight import (
        _read_root_relative_bytes,
    )

    try:
        return _read_root_relative_bytes(root, path)
    except (OSError, ValueError):
        return None


def _read_yaml_snapshot(raw: bytes | None) -> dict[str, Any]:
    if raw is None:
        return {}
    try:
        data = yaml.safe_load(raw.decode("utf-8")) or {}
    except (UnicodeDecodeError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _bound_file_reference_path(root: Path, reference: Any) -> Path | None:
    if not isinstance(reference, dict):
        return None
    raw_path = reference.get("path")
    expected_hash = reference.get("sha256")
    if (
        not isinstance(raw_path, str)
        or not raw_path.strip()
        or Path(raw_path).is_absolute()
        or not isinstance(expected_hash, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
    ):
        return None
    lexical_path = root / raw_path
    raw = _root_snapshot_bytes(root, lexical_path)
    if raw is None or hashlib.sha256(raw).hexdigest() != expected_hash:
        return None
    try:
        path = lexical_path.resolve()
        path.relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    if not path.is_file() or path.is_symlink():
        return None
    return path


def _v2_candidate_identity_matches(
    root: Path,
    request: dict[str, Any],
    session: dict[str, Any],
    task_id: str,
) -> bool:
    job_kind = request.get("job_kind")
    run_mode = request.get("run_mode")
    if (
        not isinstance(job_kind, str)
        or not isinstance(run_mode, str)
        or (job_kind, run_mode) not in _V2_CANDIDATE_JOB_MODES
        or session.get("job_kind") != job_kind
        or session.get("run_mode") != run_mode
    ):
        return False
    if (
        type(request.get("schema_version")) is not int
        or request.get("schema_version") != 1
        or type(session.get("schema_version")) is not int
        or session.get("schema_version") != 1
        or request.get("project") != "Crown_of_Ash"
        or session.get("project") != "Crown_of_Ash"
        or request.get("task_id") != session.get("task_id")
        or request.get("task_id") != task_id
        or request.get("candidate_only") is not True
        or session.get("candidate_only") is not True
        or request.get("production_modified") is not False
        or session.get("production_modified") is not False
        or request.get("external_context_approval_required") is not True
        or session.get("external_context_approval_required") is not True
    ):
        return False
    chapter_id = request.get("chapter_id")
    if (
        not isinstance(chapter_id, int)
        or isinstance(chapter_id, bool)
        or chapter_id < 1
        or type(session.get("chapter_id")) is not int
        or session.get("chapter_id") != chapter_id
    ):
        return False
    if job_kind == "narrative_generation":
        return True
    if any(
        not isinstance(request.get(key), str)
        or _V2_REVISION_IDENTIFIER.fullmatch(str(request[key])) is None
        or session.get(key) != request[key]
        for key in _V2_REVISION_IDENTITY_FIELDS
        if key != "lease_expires_at"
    ):
        return False
    lease_expires_at = request.get("lease_expires_at")
    if not isinstance(lease_expires_at, str):
        return False
    try:
        parsed_expiry = datetime.fromisoformat(
            str(lease_expires_at).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return False
    if parsed_expiry.tzinfo is None or session.get("lease_expires_at") != lease_expires_at:
        return False
    if request["task_id"] in {
        request["source_job_id"],
        request["source_run_id"],
        request["triggered_by_audit_id"],
    } or request["triggered_by_audit_id"] == request["source_run_id"]:
        return False
    rewrite_count = request.get("automatic_rewrite_count")
    rewrite_number = request.get("automatic_rewrite_number")
    if (
        not isinstance(rewrite_count, int)
        or isinstance(rewrite_count, bool)
        or rewrite_count not in {0, 1}
        or not isinstance(rewrite_number, int)
        or isinstance(rewrite_number, bool)
        or rewrite_number != rewrite_count + 1
        or session.get("automatic_rewrite_count") != rewrite_count
        or session.get("automatic_rewrite_number") != rewrite_number
        or type(session.get("automatic_rewrite_count")) is not int
        or type(session.get("automatic_rewrite_number")) is not int
    ):
        return False
    attempt_receipt = request.get("attempt_receipt")
    if session.get("attempt_receipt") != attempt_receipt:
        return False
    receipt_path = _bound_file_reference_path(root, attempt_receipt)
    if receipt_path is None:
        return False
    from agent_runtime.narrative.production.revision_attempts import (
        validate_revision_attempt_receipt,
    )

    return not validate_revision_attempt_receipt(
        root=root,
        project="Crown_of_Ash",
        request=request,
        receipt_path=receipt_path,
    )


def _draft_metrics(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    nonempty_lines = [line for line in text.splitlines() if line.strip()]
    words = text.split()
    return {
        "exists": path.exists(),
        "bytes": len(text.encode("utf-8")),
        "lines": len(text.splitlines()),
        "nonempty_lines": len(nonempty_lines),
        "word_like_tokens": len(words),
        "has_heading": text.lstrip().startswith("#"),
    }


def _production_manuscript_files(project_root: Path) -> list[str]:
    manuscript_root = project_root / "production" / "manuscript"
    if not manuscript_root.exists():
        return []
    return [
        str(path.relative_to(project_root))
        for path in sorted(manuscript_root.rglob("*"))
        if path.is_file() and path.name != ".gitkeep"
    ]


def production_manuscript_files(project_root: Path) -> list[str]:
    """Public candidate-boundary check shared by background delivery workers."""
    return _production_manuscript_files(project_root)


def build_crown_live_candidate_audit(
    root: Path,
    *,
    task_id: str = DEFAULT_CROWN_LIVE_RUN,
) -> dict[str, Any]:
    """Build an evidence-only audit for the known Crown live candidate run."""
    root = root.resolve()
    project_root = root / "projects" / "Crown_of_Ash"
    run_dir = project_root / "runs" / task_id
    v2_request_path = run_dir / "narrative_v2_writer_request.yml"
    if v2_request_path.exists() or v2_request_path.is_symlink():
        return _build_crown_v2_live_candidate_audit(
            root,
            project_root,
            run_dir,
            task_id,
        )
    required = [
        "chapter_packet.yml",
        "fiction_draft.md",
        "continuity_ledger.yml",
        "state_transition_proposal.yml",
        "narrative_delivery_receipt.yml",
    ]
    missing = [name for name in required if not (run_dir / name).exists()]
    delivery = validate_narrative_delivery(run_dir)
    packet = _read_yaml(run_dir / "chapter_packet.yml")
    ledger = _read_yaml(run_dir / "continuity_ledger.yml")
    proposal = _read_yaml(run_dir / "state_transition_proposal.yml")
    receipt = _read_yaml(run_dir / "narrative_delivery_receipt.yml")
    draft = _draft_metrics(run_dir / "fiction_draft.md")
    from agent_runtime.narrative.quality.prose_conventions import (
        evaluate_prose_conventions,
    )

    prose_conventions = evaluate_prose_conventions(
        (run_dir / "fiction_draft.md").read_text(
            encoding="utf-8", errors="replace"
        )
        if (run_dir / "fiction_draft.md").is_file()
        else "",
        chapter_context={"chapter": packet.get("chapter")},
    )
    production_files = _production_manuscript_files(project_root)

    checks = [
        {
            "id": "required_files_present",
            "status": "pass" if not missing else "fail",
            "missing": missing,
        },
        {
            "id": "delivery_protocol_valid",
            "status": "pass" if delivery.get("valid") is True else "fail",
            "delivery": delivery,
        },
        {
            "id": "draft_substantial",
            "status": "pass" if draft["lines"] >= 100 and draft["bytes"] >= 5000 else "fail",
            "metrics": draft,
        },
        {
            "id": "chapter_packet_reset_baseline",
            "status": "pass"
            if packet.get("chapter") == 1
            and packet.get("baseline_mode") == "reset"
            and packet.get("previous_chapters") == []
            else "fail",
            "chapter": packet.get("chapter"),
            "baseline_mode": packet.get("baseline_mode"),
            "previous_chapters": packet.get("previous_chapters"),
        },
        {
            "id": "continuity_ledger_candidate_scope",
            "status": "pass"
            if ledger.get("schema_version") == 1
            and ledger.get("chapter") == 1
            and ledger.get("baseline_mode") == "reset"
            and isinstance(ledger.get("timeline"), dict)
            else "fail",
            "chapter": ledger.get("chapter"),
            "baseline_mode": ledger.get("baseline_mode"),
            "timeline": ledger.get("timeline"),
        },
        {
            "id": "state_transition_candidate_only",
            "status": "pass"
            if proposal.get("status") == "candidate"
            and proposal.get("requires_user_promotion") is True
            and all(event.get("scope") == "candidate_only" for event in proposal.get("events", []) if isinstance(event, dict))
            else "fail",
            "proposal_status": proposal.get("status"),
            "requires_user_promotion": proposal.get("requires_user_promotion"),
            "events": proposal.get("events", []),
        },
        {
            "id": "receipt_passes",
            "status": "pass" if receipt.get("status") == "pass" and receipt.get("delivery_check", {}).get("valid") is True else "fail",
            "receipt_status": receipt.get("status"),
            "delivery_check": receipt.get("delivery_check"),
        },
        {
            "id": "prose_conventions",
            "status": "pass"
            if prose_conventions.get("status") == "pass"
            else "fail",
            "result": prose_conventions,
        },
        {
            "id": "production_manuscript_not_modified",
            "status": "pass" if not production_files else "fail",
            "production_manuscript_files": list(production_files),
        },
    ]
    issues = [check for check in checks if check.get("status") != "pass"]
    return {
        "schema_version": 1,
        "report_type": "agentlab_crown_live_candidate_audit",
        "root": str(root),
        "project": "Crown_of_Ash",
        "task_id": task_id,
        "run_dir": str(run_dir),
        "status": "pass" if not issues else "fail",
        "checks": checks,
        "evidence": [str(run_dir / name) for name in required],
        "summary": {
            "draft_lines": draft["lines"],
            "draft_bytes": draft["bytes"],
            "candidate_chapter": packet.get("chapter"),
            "candidate_only": proposal.get("status") == "candidate",
            "production_manuscript_files": list(production_files),
        },
        "issues": issues,
    }


def _build_crown_v2_live_candidate_audit(
    root: Path,
    project_root: Path,
    run_dir: Path,
    task_id: str,
) -> dict[str, Any]:
    """Audit the prose-only v2 contract without requiring legacy Writer files."""
    from agent_runtime.narrative.quality.prose_length import (
        evaluate_han_character_contract,
        normalize_han_character_contract,
    )
    from agent_runtime.narrative.quality.prose_conventions import (
        evaluate_prose_conventions,
    )

    required = (
        "narrative_v2_writer_request.yml",
        "narrative_v2_writer_session_receipt.yml",
        "fiction_draft.md",
        "writer_execution_receipt.yml",
        "writer_v2_output_contract.yml",
    )
    snapshots = {
        name: _root_snapshot_bytes(root, run_dir / name)
        for name in required
    }
    missing = [name for name, raw in snapshots.items() if raw is None]
    request_path = run_dir / "narrative_v2_writer_request.yml"
    request = _read_yaml_snapshot(snapshots[request_path.name])
    session = _read_yaml_snapshot(
        snapshots["narrative_v2_writer_session_receipt.yml"]
    )
    output = _read_yaml_snapshot(snapshots["writer_v2_output_contract.yml"])
    execution = _read_yaml_snapshot(snapshots["writer_execution_receipt.yml"])
    draft_snapshot = snapshots["fiction_draft.md"]
    prose = draft_snapshot.decode("utf-8", errors="replace") if draft_snapshot is not None else ""
    prose_hash = hashlib.sha256(draft_snapshot).hexdigest() if draft_snapshot is not None else ""
    receipt_length_contract = normalize_han_character_contract(
        session.get("prose_length_contract")
    )
    length_contract = _v2_length_contract_from_brief(root, request)
    receipt_length_matches = (
        "prose_length_contract" not in session
        or (
            receipt_length_contract is not None
            and receipt_length_contract == length_contract
        )
    )
    length_result = evaluate_han_character_contract(prose, length_contract)
    prose_conventions = evaluate_prose_conventions(
        prose,
        chapter_context={"chapter": request.get("chapter_id")},
    )
    identity_matches = _v2_candidate_identity_matches(
        root,
        request,
        session,
        task_id,
    )
    request_snapshot = snapshots[request_path.name]
    request_hash_matches = request_snapshot is not None and session.get(
        "request_sha256"
    ) == hashlib.sha256(request_snapshot).hexdigest()
    contract_hashes_match = bool(prose_hash) and all(
        value == prose_hash
        for value in (
            output.get("prose_sha256"),
            execution.get("prose_sha256"),
        )
    )
    agentlab_execution_receipt_valid = bool(
        execution.get("schema_version") == 2
        and execution.get("issuer") == "AgentLab"
        and execution.get("issuer_role") == "writer_contract_validator"
        and execution.get("writer_cannot_overwrite") is True
        and all(
            str(execution.get(key) or "").strip()
            for key in (
                "observed_provider",
                "observed_model",
                "observed_call_id",
            )
        )
    )
    production_files = _production_manuscript_files(project_root)
    draft_clean = bool(
        prose.lstrip().startswith("#")
        and "AGENTLAB_EDIT" not in prose
        and "```yaml" not in prose
    )
    snapshot_stable = not missing and all(
        _root_snapshot_bytes(root, run_dir / name) == raw
        for name, raw in snapshots.items()
    )
    checks = [
        {
            "id": "v2_prose_only_artifacts",
            "status": "pass" if not missing else "fail",
            "missing": missing,
        },
        {
            "id": "v2_artifact_snapshot_stable",
            "status": "pass" if snapshot_stable else "fail",
        },
        {
            "id": "v2_session_identity_and_request_hash",
            "status": "pass" if identity_matches and request_hash_matches else "fail",
            "identity_matches": identity_matches,
            "request_hash_matches": request_hash_matches,
        },
        {
            "id": "v2_output_contract_and_hashes",
            "status": "pass"
            if output.get("status") == "pass"
            and output.get("candidate_only") is True
            and output.get("production_modified") is False
            and output.get("issues") == []
            and output.get("writer_execution_receipt")
            == "writer_execution_receipt.yml"
            and contract_hashes_match
            and agentlab_execution_receipt_valid
            else "fail",
            "output_status": output.get("status"),
            "hashes_match": contract_hashes_match,
            "agentlab_execution_receipt_valid": agentlab_execution_receipt_valid,
        },
        {
            "id": "prose_length_contract",
            "status": "pass"
            if length_result["status"] == "pass" and receipt_length_matches
            else "fail",
            "unit": (length_result.get("contract") or {}).get("unit"),
            "minimum": (length_result.get("contract") or {}).get("minimum"),
            "maximum": (length_result.get("contract") or {}).get("maximum"),
            "observed": length_result["han_character_count"],
            "issue": length_result["issue"],
            "receipt_matches_hash_bound_brief": receipt_length_matches,
        },
        {
            "id": "draft_is_prose_only",
            "status": "pass" if draft_clean else "fail",
        },
        {
            "id": "prose_conventions",
            "status": "pass"
            if prose_conventions.get("status") == "pass"
            else "fail",
            "result": prose_conventions,
        },
        {
            "id": "production_manuscript_not_modified",
            "status": "pass" if not production_files else "fail",
            "production_manuscript_files": list(production_files),
        },
    ]
    issues = [check for check in checks if check["status"] != "pass"]
    return {
        "schema_version": 1,
        "report_type": "agentlab_crown_live_candidate_audit",
        "contract_version": 2,
        "root": str(root),
        "project": "Crown_of_Ash",
        "task_id": task_id,
        "candidate_sha256": prose_hash,
        "run_dir": str(run_dir),
        "status": "pass" if not issues else "fail",
        "checks": checks,
        "evidence": [str(run_dir / name) for name in required],
        "summary": {
            "draft_lines": len(prose.splitlines()),
            "draft_bytes": len(prose.encode("utf-8")),
            "han_character_count": length_result["han_character_count"],
            "candidate_chapter": request.get("chapter_id"),
            "candidate_only": output.get("candidate_only") is True,
            "production_manuscript_files": list(production_files),
        },
        "issues": issues,
    }


def _v2_length_contract_from_brief(
    root: Path,
    request: dict[str, Any],
) -> dict[str, Any] | None:
    from agent_runtime.narrative.quality.prose_length import (
        build_han_character_contract,
    )

    ref = request.get("creative_brief_source")
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        return None
    try:
        path = (root / ref["path"]).resolve()
        path.relative_to(root)
    except (OSError, ValueError):
        return None
    if not path.is_file() or path.is_symlink():
        return None
    if ref.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
        return None
    brief = _read_yaml(path)
    target = brief.get("target_character_range") or brief.get("word_count_target")
    return build_han_character_contract(target)


def write_crown_live_candidate_audit(root: Path, out: Path, *, task_id: str = DEFAULT_CROWN_LIVE_RUN) -> dict[str, Any]:
    report = build_crown_live_candidate_audit(root, task_id=task_id)
    write_report_yaml(out, report, root)
    return report


def _completion_task_id(chapter: int, eval_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", eval_id).strip("_-") or "eval"
    return f"task_narrative_eval_ch{chapter:02d}_{cleaned}"[:85]


def _candidate_sources(task_id: str) -> list[str]:
    return [
        f"runs/{task_id}/fiction_draft.md",
        f"runs/{task_id}/continuity_ledger.yml",
        f"runs/{task_id}/state_transition_proposal.yml",
    ]


def _model_label(log_path: Path) -> str | None:
    if not log_path.is_file():
        return None
    labels = re.findall(
        r'Propagating selected model override to backend: label="([^"]+)"',
        log_path.read_text(encoding="utf-8", errors="replace"),
    )
    return labels[-1] if labels else None


def validate_writer_execution_contract(run_dir: Path, task_id: str) -> dict[str, Any]:
    """Validate Writer provenance against the execution contract recorded by the run."""
    workflow = _read_yaml(run_dir / "workflow_plan.yml")
    guard = _read_yaml(run_dir / "live_writer_role_session_guard.yml")
    chain_path = run_dir / "model_execution_chain_writer.yml"
    chain = _read_yaml(chain_path)

    included_agents = workflow.get("included_agents")
    writer_agent = (
        included_agents.get("Writer")
        if isinstance(included_agents, dict)
        and isinstance(included_agents.get("Writer"), dict)
        else {}
    )
    model_profiles = workflow.get("model_profiles")
    writer_model = (
        model_profiles.get("Writer")
        if isinstance(model_profiles, dict)
        and isinstance(model_profiles.get("Writer"), dict)
        else {}
    )
    expected_provider = writer_model.get("provider")
    expected_model = writer_model.get("model")
    expected_worker = writer_agent.get("execution_owner") or writer_model.get(
        "cli_agent"
    )
    legacy_agy = (
        expected_provider == "agy-gemini-oauth"
        and expected_model == "gemini-3.5-flash-high"
    )
    if not expected_worker and legacy_agy:
        expected_worker = "agy"

    issues: list[str] = []
    if workflow.get("task_id") != task_id:
        issues.append("workflow_task_id")
    if not expected_provider or not expected_model:
        issues.append("workflow_writer_model")
    if not expected_worker:
        issues.append("workflow_execution_owner")
    if guard.get("status") != "pass":
        issues.append("role_session_guard_status")
    if guard.get("role") != "Writer":
        issues.append("role_session_guard_role")
    if guard.get("task_id") != task_id:
        issues.append("role_session_guard_task_id")
    if guard.get("project") != "Crown_of_Ash":
        issues.append("role_session_guard_project")
    if expected_worker and guard.get("worker") != expected_worker:
        issues.append("role_session_guard_worker")

    mode = "model_execution_chain"
    observed_provider = None
    observed_model = None
    if chain_path.is_file():
        final = chain.get("final") if isinstance(chain.get("final"), dict) else {}
        attempts = chain.get("attempts") if isinstance(chain.get("attempts"), list) else []
        observed_provider = final.get("provider")
        observed_model = final.get("model")
        if chain.get("role") != "Writer":
            issues.append("model_chain_role")
        if chain.get("status") != "pass":
            issues.append("model_chain_status")
        if chain.get("fallback_used") is not False:
            issues.append("model_chain_fallback")
        if any(
            isinstance(attempt, dict) and attempt.get("fallback_detected") is True
            for attempt in attempts
        ):
            issues.append("model_chain_attempt_fallback")
        if final.get("status") != "pass":
            issues.append("model_chain_final_status")
        if observed_provider != expected_provider:
            issues.append("model_chain_provider")
        if observed_model != expected_model:
            issues.append("model_chain_model")
    else:
        mode = "legacy_agy_log"
        observed_provider = "agy-gemini-oauth" if legacy_agy else None
        observed_model = "gemini-3.5-flash-high" if legacy_agy else None
        if not legacy_agy:
            issues.append("model_chain_missing")
        if _model_label(run_dir / "command_logs" / "agy_cli_agent.log") != AGY_HIGH_MODEL_LABEL:
            issues.append("legacy_agy_model_label")

    return {
        "status": "pass" if not issues else "fail",
        "mode": mode,
        "expected": {
            "worker": expected_worker,
            "provider": expected_provider,
            "model": expected_model,
        },
        "observed": {
            "worker": guard.get("worker"),
            "provider": observed_provider,
            "model": observed_model,
        },
        "fallback_used": chain.get("fallback_used") if chain_path.is_file() else False,
        "issues": issues,
    }


def build_crown_completion_batch_audit(
    root: Path,
    *,
    eval_id: str,
    through_chapter: int,
) -> dict[str, Any]:
    """Audit one resumable Crown candidate chain without calling a provider."""
    if through_chapter < 1:
        raise ValueError("through_chapter must be at least 1")

    root = root.resolve()
    project_root = root / "projects" / "Crown_of_Ash"
    runs_root = project_root / "runs"
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    chapters: list[dict[str, Any]] = []
    normalizations: list[dict[str, Any]] = []
    retry_ledgers: list[dict[str, Any]] = []
    local_recoveries: list[dict[str, Any]] = []
    rejected_attempts: list[str] = []
    repetition_findings: list[dict[str, Any]] = []
    prior_drafts: list[tuple[int, set[str]]] = []
    seen_drafts: dict[str, int] = {}
    cumulative_events = 0
    fact_ledger_started = False

    for chapter in range(1, through_chapter + 1):
        task_id = _completion_task_id(chapter, eval_id)
        run_dir = runs_root / task_id
        missing = [name for name in BATCH_REQUIRED_FILES if not (run_dir / name).is_file()]
        chapter_issues: list[str] = [f"missing:{name}" for name in missing]
        if missing:
            issues.extend(
                {"chapter": chapter, "check": "required_file", "message": item}
                for item in chapter_issues
            )
            chapters.append({"chapter": chapter, "task_id": task_id, "status": "fail", "issues": chapter_issues})
            continue

        packet = _read_yaml(run_dir / "chapter_packet.yml")
        ledger = _read_yaml(run_dir / "continuity_ledger.yml")
        proposal = _read_yaml(run_dir / "state_transition_proposal.yml")
        receipt = _read_yaml(run_dir / "narrative_delivery_receipt.yml")
        contract = _read_yaml(run_dir / "writer_output_contract.yml")
        writer_execution = validate_writer_execution_contract(run_dir, task_id)
        delivery = validate_narrative_delivery(run_dir)
        draft = (run_dir / "fiction_draft.md").read_text(encoding="utf-8", errors="replace")
        intent = packet.get("chapter_intent") if isinstance(packet.get("chapter_intent"), dict) else {}
        hard_range = intent.get("hard_character_range") or [3000, 8000]
        expected_baseline = "reset" if chapter == 1 else "continuation"
        previous = packet.get("previous_candidate_sources")
        if previous is None:
            previous = packet.get("previous_chapters") or []
        expected_previous = [] if chapter == 1 else _candidate_sources(
            _completion_task_id(chapter - 1, eval_id)
        )
        events = proposal.get("events") if isinstance(proposal.get("events"), list) else []
        checks = {
            "delivery_valid": delivery.get("valid") is True,
            "packet_chapter": packet.get("chapter") == chapter,
            "baseline": packet.get("baseline_mode") == expected_baseline
            and ledger.get("baseline_mode") == expected_baseline,
            "previous_chain": previous == expected_previous,
            "ledger_chapter": ledger.get("chapter") == chapter,
            "ledger_lists": all(isinstance(ledger.get(name), list) and ledger.get(name) for name in BATCH_LEDGER_LISTS),
            "contract": contract.get("status") == "pass",
            "draft_range": isinstance(hard_range, list)
            and len(hard_range) == 2
            and all(isinstance(value, int) for value in hard_range)
            and hard_range[0] <= len(draft) <= hard_range[1],
            "draft_heading": next((line for line in draft.splitlines() if line.strip()), "").startswith("#"),
            "proposal": proposal.get("chapter") == chapter
            and proposal.get("status") == "candidate"
            and proposal.get("requires_user_promotion") is True
            and bool(events)
            and all(isinstance(event, dict) and event.get("scope") == "candidate_only" for event in events),
            "receipt": receipt.get("status") == "pass"
            and receipt.get("candidate_only") is True
            and all((receipt.get("checks") or {}).get(name) == "pass" for name in BATCH_RECEIPT_CHECKS),
            "writer_execution_contract": writer_execution.get("status") == "pass",
        }
        draft_hash = hashlib.sha256(draft.encode("utf-8")).hexdigest()
        checks["unique_draft"] = draft_hash not in seen_drafts
        seen_drafts[draft_hash] = chapter

        draft_paragraphs = substantive_paragraphs(draft)
        for source_chapter, previous_paragraphs in prior_drafts:
            evidence = repetition_evidence_from_paragraphs(
                draft_paragraphs,
                previous_paragraphs,
            )
            if not evidence["blocking"]:
                continue
            finding = {
                "chapter": chapter,
                "source_chapter": source_chapter,
                **evidence,
            }
            repetition_findings.append(finding)
            if "cross_chapter_repetition" not in chapter_issues:
                chapter_issues.append("cross_chapter_repetition")
            issues.append(
                {
                    "chapter": chapter,
                    "check": "cross_chapter_repetition",
                    "message": (
                        f"substantive prose repeats chapter {source_chapter}: "
                        f"passages={evidence['passage_count']}, "
                        f"characters={evidence['repeated_characters']}, "
                        f"longest={evidence['longest_passage_characters']}"
                    ),
                }
            )
        prior_drafts.append((chapter, draft_paragraphs))

        fact_path = run_dir / "candidate_fact_ledger.yml"
        if fact_path.is_file():
            fact_ledger_started = True
            facts = _read_yaml(fact_path)
            checks["candidate_fact_ledger"] = (
                facts.get("through_chapter") == chapter - 1
                and facts.get("event_count") == cumulative_events
                and facts.get("promoted") is False
            )
        elif fact_ledger_started:
            checks["candidate_fact_ledger"] = False
        elif chapter > 1:
            warnings.append(
                {
                    "chapter": chapter,
                    "check": "candidate_fact_ledger",
                    "message": "candidate fact ledger predates rolling-ledger activation",
                }
            )

        for check, passed in checks.items():
            if not passed:
                chapter_issues.append(check)
                issues.append({"chapter": chapter, "check": check, "message": "check failed"})

        normalizations.extend(
            {"chapter": chapter, **item}
            for item in (contract.get("normalizations") or [])
            if isinstance(item, dict)
        )
        retry_path = run_dir / "writer_retry_ledger.yml"
        if retry_path.is_file():
            retry = _read_yaml(retry_path)
            retry_ledgers.append(
                {
                    "chapter": chapter,
                    "status": retry.get("status"),
                    "attempt_count": len(retry.get("attempts") or []),
                }
            )
        recovery_path = run_dir / "local_materialization_recovery.yml"
        if recovery_path.is_file():
            recovery = _read_yaml(recovery_path)
            local_recoveries.append(
                {"chapter": chapter, "status": recovery.get("status"), "path": str(recovery_path.relative_to(project_root))}
            )
        rejected_attempts.extend(
            str(path.relative_to(project_root))
            for path in sorted((run_dir / "rejected_attempts").glob("*/rejection.yml"))
        )
        chapters.append(
            {
                "chapter": chapter,
                "task_id": task_id,
                "status": "pass" if not chapter_issues else "fail",
                "draft_characters": len(draft),
                "candidate_event_count": len(events),
                "writer_execution": writer_execution,
                "issues": chapter_issues,
            }
        )
        cumulative_events += len(events)

    production_files = _production_manuscript_files(project_root)
    if production_files:
        issues.append(
            {
                "chapter": None,
                "check": "production_manuscript_not_modified",
                "message": "candidate generation wrote production manuscript files",
            }
        )
    lengths = [item["draft_characters"] for item in chapters if "draft_characters" in item]
    return {
        "schema_version": 1,
        "report_type": "agentlab_crown_completion_batch_audit",
        "project": "Crown_of_Ash",
        "eval_id": eval_id,
        "chapter_range": [1, through_chapter],
        "status": "pass" if not issues else "fail",
        "summary": {
            "selected_chapter_count": through_chapter,
            "valid_chapter_count": sum(item.get("status") == "pass" for item in chapters),
            "total_candidate_events": cumulative_events,
            "draft_character_range": [min(lengths), max(lengths)] if lengths else None,
            "normalization_count": sum(int(item.get("count") or 0) for item in normalizations),
            "retry_ledger_count": len(retry_ledgers),
            "local_recovery_count": len(local_recoveries),
            "rejected_attempt_count": len(rejected_attempts),
            "repetition_failure_count": len(repetition_findings),
            "repetition_chapter_count": len(
                {item["chapter"] for item in repetition_findings}
            ),
            "production_manuscript_files": production_files,
        },
        "chapters": chapters,
        "normalizations": normalizations,
        "retry_ledgers": retry_ledgers,
        "local_recoveries": local_recoveries,
        "rejected_attempts": rejected_attempts,
        "repetition_findings": repetition_findings,
        "warnings": warnings,
        "issues": issues,
    }


def write_crown_completion_batch_audit(
    root: Path,
    out: Path,
    *,
    eval_id: str,
    through_chapter: int,
) -> dict[str, Any]:
    report = build_crown_completion_batch_audit(
        root,
        eval_id=eval_id,
        through_chapter=through_chapter,
    )
    write_report_yaml(out, report, root)
    return report
