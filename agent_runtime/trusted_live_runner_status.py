"""Check whether trusted live runner outputs have returned."""

from __future__ import annotations

from pathlib import Path
import shutil
import shlex
from typing import Any

import yaml

try:
    from agent_runtime.report_sanitizer import write_report_yaml
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from report_sanitizer import write_report_yaml

try:
    from audit_helpers import trusted_live_acceptance_blocker
except ModuleNotFoundError:
    from agent_runtime.audit_helpers import trusted_live_acceptance_blocker


LOCAL_GROK_CLI_ADAPTERS = {"local_grok_cli", "grok_cli_oauth"}
PROMPT_FLAGS = {"-p", "--prompt", "-z", "--oneshot"}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _resolve_path(root: Path, path_text: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = root / path
    return path


def _path_exists(root: Path, path_text: str) -> bool:
    return _resolve_path(root, path_text).exists()


def _required_path(required: list[str], filename: str) -> str:
    return next((path for path in required if path.endswith(filename)), "")


def _rel_path_text(root: Path, path: Path) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(root.resolve(strict=False)))
    except ValueError:
        return str(path)


def _check(status: bool, id_: str, message: str, **details: Any) -> dict[str, Any]:
    return {
        "id": id_,
        "status": "pass" if status else "fail",
        "message": message,
        **details,
    }


def _without_none_values(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _text_content(root: Path, path_text: str) -> str:
    if not path_text:
        return ""
    path = _resolve_path(root, path_text)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace").strip()


def _text_size(root: Path, path_text: str) -> int:
    return len(_text_content(root, path_text))


def _artifact_paths_exist(root: Path, paths: list[Any]) -> bool:
    path_texts = [str(path).strip() for path in paths if str(path).strip()]
    if not path_texts or len(path_texts) != len(paths):
        return False
    return all(_resolve_path(root, path).exists() for path in path_texts)


def _artifact_paths_are_nonempty_files(root: Path, paths: list[Any]) -> bool:
    path_texts = [str(path).strip() for path in paths if str(path).strip()]
    if not path_texts or len(path_texts) != len(paths):
        return False
    for path_text in path_texts:
        path = _resolve_path(root, path_text)
        if not path.is_file() or path.stat().st_size <= 0:
            return False
    return True


def _artifact_paths_under_dir(root: Path, paths: list[Any], dir_text: str) -> bool:
    path_texts = [str(path).strip() for path in paths if str(path).strip()]
    if not path_texts or len(path_texts) != len(paths) or not dir_text:
        return False
    base = _resolve_path(root, dir_text).resolve(strict=False)
    for path_text in path_texts:
        resolved = _resolve_path(root, path_text).resolve(strict=False)
        try:
            resolved.relative_to(base)
        except ValueError:
            return False
        if resolved == base:
            return False
    return True


def _longform_eval_matches_run_dir(root: Path, eval_report: dict[str, Any], draft_path: str) -> dict[str, Any]:
    if not draft_path:
        return {"matches": False, "expected_run_dir": "", "reported_run_dirs": []}
    expected_path = _resolve_path(root, draft_path).parent.resolve(strict=False)
    expected_run_dir = _rel_path_text(root, expected_path)
    layers = eval_report.get("layers") if isinstance(eval_report.get("layers"), dict) else {}
    l2 = layers.get("L2_real_chapter_sample") if isinstance(layers.get("L2_real_chapter_sample"), dict) else {}
    chapters = l2.get("chapters") if isinstance(l2.get("chapters"), list) else []
    reported_run_dirs = [
        str(item.get("run_dir") or "")
        for item in chapters
        if isinstance(item, dict) and item.get("run_dir")
    ]
    matches = any(
        _resolve_path(root, reported).resolve(strict=False) == expected_path
        for reported in reported_run_dirs
    )
    return {
        "matches": matches,
        "expected_run_dir": expected_run_dir,
        "reported_run_dirs": reported_run_dirs,
    }


def _longform_current_sample_passed(eval_report: dict[str, Any]) -> bool:
    if eval_report.get("status") == "pass":
        return True
    if eval_report.get("status") != "warn":
        return False
    layers = eval_report.get("layers") if isinstance(eval_report.get("layers"), dict) else {}
    return all(
        isinstance(layers.get(layer_id), dict)
        and layers[layer_id].get("status") == "pass"
        for layer_id in (
            "L0_fact_source_health",
            "L2_real_chapter_sample",
            "L3_series_scale_simulation",
        )
    )


def _outbound_context_checks(
    root: Path,
    manifest_path: str,
    *,
    expected_role: str,
) -> list[dict[str, Any]]:
    manifest = _read_yaml(_resolve_path(root, manifest_path)) if manifest_path else {}
    payload = manifest.get("payload") if isinstance(manifest.get("payload"), dict) else {}
    boundary = (
        manifest.get("context_boundary")
        if isinstance(manifest.get("context_boundary"), dict)
        else {}
    )
    authorization = (
        manifest.get("authorization")
        if isinstance(manifest.get("authorization"), dict)
        else {}
    )
    approval_ok = (
        authorization.get("approval_required") is not True
        or authorization.get("approval_observed") is True
    )
    return [
        _check(
            manifest.get("status") == "pass" and manifest.get("execution_allowed") is True,
            "outbound_context_manifest_passed",
            "provider-bound context manifest passed before execution",
            manifest_status=manifest.get("status"),
        ),
        _check(
            manifest.get("role") == expected_role,
            "outbound_context_role_matches",
            "outbound context manifest belongs to the expected AgentLab role",
            manifest_role=manifest.get("role"),
            expected_role=expected_role,
        ),
        _check(
            boundary.get("sealed_context") is True
            and boundary.get("exact_payload_hashed") is True,
            "outbound_context_exact_and_sealed",
            "provider-bound context was sealed and exact-payload hashed",
        ),
        _check(
            _safe_int(payload.get("secret_pattern_hit_count")) == 0,
            "outbound_context_secret_scan_clean",
            "provider-bound context contains no recognized secret pattern",
            secret_pattern_hit_count=_safe_int(payload.get("secret_pattern_hit_count")),
        ),
        _check(
            len(str(payload.get("sha256") or "")) == 64 and _safe_int(payload.get("bytes")) > 0,
            "outbound_context_digest_present",
            "provider-bound context has a non-empty SHA-256 digest",
        ),
        _check(
            approval_ok,
            "outbound_context_approval_satisfied",
            "explicit approval was observed whenever this run required it",
            approval_required=authorization.get("approval_required"),
            approval_observed=authorization.get("approval_observed"),
        ),
    ]


def _narrative_artifact_qc(root: Path, required: list[str]) -> dict[str, Any]:
    draft_path = _required_path(required, "fiction_draft.md")
    receipt_path = _required_path(required, "narrative_delivery_receipt.yml")
    transition_path = _required_path(required, "state_transition_proposal.yml")
    ledger_path = _required_path(required, "continuity_ledger.yml")
    eval_path = _required_path(required, "longform_eval_report.yml")
    outbound_manifest_path = _required_path(required, "outbound_context_manifest_writer.yml")
    writer_contract_path = _required_path(required, "writer_output_contract.yml")

    receipt = _read_yaml(_resolve_path(root, receipt_path)) if receipt_path else {}
    transition = _read_yaml(_resolve_path(root, transition_path)) if transition_path else {}
    ledger = _read_yaml(_resolve_path(root, ledger_path)) if ledger_path else {}
    eval_report = _read_yaml(_resolve_path(root, eval_path)) if eval_path else {}
    writer_contract = _read_yaml(_resolve_path(root, writer_contract_path)) if writer_contract_path else {}
    delivery_check = receipt.get("delivery_check") if isinstance(receipt.get("delivery_check"), dict) else {}
    events = transition.get("events") if isinstance(transition.get("events"), list) else []
    timeline = ledger.get("timeline") if isinstance(ledger.get("timeline"), dict) else {}
    draft_text = _text_content(root, draft_path)
    draft_chars = len(draft_text)
    draft_nonblank_lines = sum(1 for line in draft_text.splitlines() if line.strip())
    draft_lower = draft_text.lower()
    placeholder_free = not any(marker in draft_lower for marker in ("tbd", "placeholder", "lorem ipsum"))
    eval_run_match = _longform_eval_matches_run_dir(root, eval_report, draft_path)
    current_sample_passed = _longform_current_sample_passed(eval_report)

    checks = [
        _check(
            draft_chars >= 1200,
            "fiction_draft_substantive",
            "fiction draft contains chapter-scale substantive text",
            chars=draft_chars,
            minimum_chars=1200,
        ),
        _check(
            draft_nonblank_lines >= 8,
            "fiction_draft_multiline_chapter",
            "fiction draft has multiple non-empty chapter lines",
            nonblank_lines=draft_nonblank_lines,
            minimum_nonblank_lines=8,
        ),
        _check(
            placeholder_free,
            "fiction_draft_not_placeholder",
            "fiction draft is not placeholder text",
        ),
        _check(
            receipt.get("status") == "pass" or delivery_check.get("valid") is True,
            "delivery_receipt_passed",
            "narrative delivery receipt passed",
            receipt_status=receipt.get("status"),
        ),
        _check(
            transition.get("status") == "candidate" and transition.get("requires_user_promotion") is True,
            "state_transition_candidate_only",
            "state transition proposal remains candidate-only and requires promotion",
            proposal_status=transition.get("status"),
        ),
        _check(bool(events), "state_transition_events_present", "state transition proposal records proposed events"),
        _check(
            timeline.get("monotonic") is True,
            "continuity_timeline_monotonic",
            "continuity ledger records a monotonic timeline",
            monotonic=timeline.get("monotonic"),
        ),
        _check(
            current_sample_passed,
            "longform_eval_passed",
            "formal current-run longform evaluation layers passed",
            eval_status=eval_report.get("status"),
            historical_warning_only=(
                eval_report.get("status") == "warn" and current_sample_passed
            ),
        ),
        _check(
            eval_run_match["matches"],
            "longform_eval_matches_run_dir",
            "formal longform evaluation report references the returned narrative run directory",
            expected_run_dir=eval_run_match["expected_run_dir"],
            reported_run_dirs=eval_run_match["reported_run_dirs"],
        ),
    ]
    if outbound_manifest_path:
        checks.extend(
            _outbound_context_checks(
                root,
                outbound_manifest_path,
                expected_role="Writer",
            )
        )
    if writer_contract_path:
        checks.append(
            _check(
                writer_contract.get("status") == "pass"
                and writer_contract.get("harness_generated_story_state") is False,
                "writer_output_contract_passed",
                "Writer returned and materialized every required candidate output without harness-authored story state",
                writer_contract_status=writer_contract.get("status"),
            )
        )
    return {
        "type": "narrative_live_smoke",
        "status": "pass" if all(check["status"] == "pass" for check in checks) else "fail",
        "checks": checks,
    }


def _media_artifact_qc(root: Path, expected: dict[str, Any], required: list[str]) -> dict[str, Any]:
    preflight_path = _required_path(required, "media_backend_preflight.yml")
    ledger_path = _required_path(required, "generation_ledger.yml")
    outbound_manifest_path = _required_path(required, "outbound_context_manifest_media.yml")
    preflight = _read_yaml(_resolve_path(root, preflight_path)) if preflight_path else {}
    ledger = _read_yaml(_resolve_path(root, ledger_path)) if ledger_path else {}
    out_dir = str(expected.get("out_dir") or "")
    generated_assets = ledger.get("generated_assets") if isinstance(ledger.get("generated_assets"), list) else []
    text_artifacts = ledger.get("text_artifacts") if isinstance(ledger.get("text_artifacts"), list) else []

    checks = [
        _check(
            preflight.get("status") in {"ready", "pass"},
            "media_preflight_ready",
            "media backend preflight is ready",
            preflight_status=preflight.get("status"),
        ),
        _check(
            preflight.get("adapter_kind") == ledger.get("adapter_kind") and bool(ledger.get("adapter_kind")),
            "media_adapter_matches_preflight",
            "generation ledger adapter matches preflight",
            preflight_adapter=preflight.get("adapter_kind"),
            ledger_adapter=ledger.get("adapter_kind"),
        ),
        _check(
            ledger.get("status") == "completed",
            "media_generation_completed",
            "generation ledger completed with real media outputs",
            ledger_status=ledger.get("status"),
        ),
        _check(
            ledger.get("artifact_generation_verified") is True,
            "media_artifact_generation_verified",
            "generation ledger verifies media artifact creation",
            artifact_generation_verified=ledger.get("artifact_generation_verified"),
        ),
        _check(
            bool(generated_assets),
            "media_generated_assets_recorded",
            "generation ledger records generated media assets",
            generated_asset_count=len(generated_assets),
            text_artifact_count=len(text_artifacts),
        ),
        _check(
            _artifact_paths_exist(root, generated_assets),
            "media_generated_assets_exist",
            "recorded generated media assets exist",
            generated_asset_count=len(generated_assets),
        ),
        _check(
            _artifact_paths_are_nonempty_files(root, generated_assets),
            "media_generated_assets_nonempty_files",
            "recorded generated media assets are non-empty files",
            generated_asset_count=len(generated_assets),
        ),
        _check(
            _artifact_paths_under_dir(root, generated_assets, out_dir),
            "media_generated_assets_under_out_dir",
            "recorded generated media assets stay under the trusted runner out_dir",
            out_dir=out_dir,
        ),
    ]
    if outbound_manifest_path:
        checks.extend(
            _outbound_context_checks(
                root,
                outbound_manifest_path,
                expected_role="ArtifactProducer",
            )
        )
    return {
        "type": "media_live_smoke",
        "status": "pass" if all(check["status"] == "pass" for check in checks) else "fail",
        "checks": checks,
    }


def _artifact_qc(root: Path, expected: dict[str, Any], required: list[str]) -> dict[str, Any]:
    expected_type = str(expected.get("type") or "")
    if expected_type == "narrative_live_smoke":
        return _narrative_artifact_qc(root, required)
    if expected_type == "media_live_smoke":
        return _media_artifact_qc(root, expected, required)
    return {"type": expected_type or "unknown", "status": "skipped", "checks": []}


def _observed_error(root: Path, expected: dict[str, Any]) -> dict[str, Any] | None:
    base_text = str(expected.get("run_dir") or expected.get("out_dir") or "")
    if not base_text:
        return None
    base = _resolve_path(root, base_text)
    candidates = [
        base / "live_generation_error.yml",
        base / "media_backend_error.yml",
        base / "USER_DECISION_REQUIRED.md",
        base / "blocked_Writer.md",
    ]
    for path in candidates:
        if not path.exists():
            continue
        if path.suffix in {".yml", ".yaml"}:
            report = _read_yaml(path)
            observed = {
                "path": str(path),
                "status": report.get("status"),
                "agent": report.get("agent"),
                "result_status": report.get("result_status"),
                "provider": report.get("provider"),
                "model": report.get("model"),
                "error": report.get("error"),
            }
            return _attach_historical_agy_session_evidence(root, path, observed)
        return {"path": str(path), "status": "present"}
    return None


def _arg_value(args: list[Any], option: str) -> str | None:
    text_args = [str(arg) for arg in args]
    try:
        idx = text_args.index(option)
    except ValueError:
        return None
    if idx + 1 >= len(text_args):
        return None
    return text_args[idx + 1]


def _current_backend_max_turns(root: Path, backend_id: str) -> str | None:
    args = _current_backend_args(root, backend_id)
    if not args:
        return None
    return _arg_value(args, "--max-turns")


def _current_backend_args(root: Path, backend_id: str) -> list[str]:
    config = _read_yaml(root / "config" / "media_generation_backends.yml")
    backend = ((config.get("backends") or {}).get(backend_id) or {})
    command_contract = backend.get("command_contract") if isinstance(backend.get("command_contract"), dict) else {}
    command = str(command_contract.get("session_smoke") or command_contract.get("oauth_smoke") or "")
    if not command:
        return []
    try:
        return shlex.split(command)
    except ValueError:
        return []


def _command_shape(args: list[Any]) -> str | None:
    if not args:
        return None
    rendered: list[str] = []
    skip_next = False
    for arg in [str(item) for item in args]:
        if skip_next:
            rendered.append("<prompt>")
            skip_next = False
            continue
        rendered.append(arg)
        if arg in PROMPT_FLAGS:
            skip_next = True
    return " ".join(rendered)


def _command_available(args: list[Any]) -> bool | None:
    if not args:
        return None
    return shutil.which(str(args[0])) is not None


def _command_path(args: list[Any]) -> str | None:
    if not args:
        return None
    return shutil.which(str(args[0]))


def _current_grok_session_smoke(root: Path, ledger_path: Path | None = None) -> dict[str, Any] | None:
    path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "grok_cli_session_smoke.yml"
    if not path.exists():
        return None
    smoke = _read_yaml(path)
    if smoke.get("backend_id") != "hermes_grok_oauth" or smoke.get("adapter_kind") not in LOCAL_GROK_CLI_ADAPTERS:
        return None
    smoke["_path"] = str(path)
    if ledger_path and ledger_path.exists():
        smoke["_is_newer_than_ledger"] = path.stat().st_mtime >= ledger_path.stat().st_mtime
    return smoke


def _historical_agy_session_smoke(root: Path, error_path: Path | None = None) -> dict[str, Any] | None:
    path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "agy_cli_session_smoke.yml"
    if not path.exists():
        return None
    smoke = _read_yaml(path)
    if smoke.get("worker") != "agy":
        return None
    smoke["_path"] = str(path)
    if error_path and error_path.exists():
        smoke["_is_newer_than_error"] = path.stat().st_mtime >= error_path.stat().st_mtime
    return smoke


def _current_agy_writer_session_probe(root: Path) -> dict[str, Any] | None:
    path = (
        root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "agy_writer_session_probe.yml"
    )
    if not path.exists():
        return None
    probe = _read_yaml(path)
    if probe.get("worker_id") != "agy":
        return None
    error_class = str(probe.get("error_class") or "").lower()
    passed = (
        probe.get("installed") is True
        and probe.get("exit_code") == 0
        and probe.get("timeout") is not True
        and error_class in {"", "none"}
    )
    probe["status"] = "pass" if passed else "blocked"
    probe["reason"] = None if passed else (error_class or "agy_writer_probe_failed")
    probe["_path"] = str(path)
    return probe


def _is_agy_localhost_bind_denied(observed_error: dict[str, Any] | None) -> bool:
    if not observed_error:
        return False
    error_text = str(observed_error.get("error") or "")
    return (
        observed_error.get("provider") == "agentlab-cli-executor"
        and observed_error.get("model") == "agy"
        and "listen tcp 127.0.0.1:0" in error_text
        and "operation not permitted" in error_text
    )


def _attach_historical_agy_session_evidence(
    root: Path,
    path: Path,
    observed: dict[str, Any],
) -> dict[str, Any]:
    if not _is_agy_localhost_bind_denied(observed):
        return observed
    observed["historical_writer_route"] = "agy"
    observed["historical_writer_route_is_current"] = False
    session_smoke = _historical_agy_session_smoke(root, path)
    if not session_smoke:
        return observed
    observed["historical_session_smoke_status"] = session_smoke.get("status")
    observed["historical_session_smoke_path"] = session_smoke.get("_path")
    observed["historical_session_smoke_created_at"] = session_smoke.get("created_at")
    observed["historical_session_smoke_newer_than_error"] = session_smoke.get(
        "_is_newer_than_error"
    )
    if session_smoke.get("reason"):
        observed["historical_session_smoke_reason"] = session_smoke.get("reason")
    return observed


def _cli_contract_health(observed_error: dict[str, Any] | None) -> dict[str, Any] | None:
    if not observed_error or observed_error.get("adapter_kind") not in LOCAL_GROK_CLI_ADAPTERS:
        return None
    entrypoint_available = observed_error.get("current_command_available")
    settings_fetch_failed = bool(observed_error.get("settings_fetch_failed"))
    transport_failure = bool(observed_error.get("transport_failure_marker_present"))
    if observed_error.get("stale_after_contract_update"):
        status = "stale_contract_evidence"
        failure_scope = "stale_media_backend_contract"
    elif observed_error.get("stale_after_session_health_pass"):
        status = "session_contract_now_passes"
        failure_scope = "stale_media_backend_ledger"
    elif transport_failure and entrypoint_available:
        status = "entrypoint_available_transport_failed"
        failure_scope = "local_grok_network_or_proxy"
    elif transport_failure:
        status = "entrypoint_unverified_transport_failed"
        failure_scope = "local_grok_network_or_proxy"
    elif settings_fetch_failed and entrypoint_available:
        status = "entrypoint_available_contract_failed"
        failure_scope = "local_grok_session_health"
    elif settings_fetch_failed:
        status = "entrypoint_unverified_contract_failed"
        failure_scope = "local_grok_session_health"
    else:
        status = "media_backend_contract_not_pass"
        failure_scope = "media_backend_live_smoke"
    return {
        "worker": "grok",
        "entrypoint_available": entrypoint_available,
        "entrypoint_path": observed_error.get("current_command_path"),
        "contract_mode": "non_interactive_prompt_contract",
        "execution_scope": "internal_local_cli_worker",
        "interactive_entrypoint_only_is_not_task_contract_proof": True,
        "settings_fetch_failed": settings_fetch_failed,
        "transport_failure_marker_present": transport_failure,
        "failure_scope": failure_scope,
        "status": status,
        "reason": observed_error.get("error"),
        "current_session_smoke_status": observed_error.get("current_session_smoke_status"),
        "current_session_smoke_path": observed_error.get("current_session_smoke_path"),
    }


def _payload_plan_args(ledger_path: Path) -> list[Any]:
    payload_plan = _read_yaml(ledger_path.parent / "media_backend_payload_plan.yml")
    args = payload_plan.get("args") if isinstance(payload_plan.get("args"), list) else []
    return args


def _payload_plan_max_turns(ledger_path: Path) -> str | None:
    args = _payload_plan_args(ledger_path)
    return _arg_value(args, "--max-turns")


def _ledger_observed_error(root: Path, required: list[str]) -> dict[str, Any] | None:
    ledger_path = next((path for path in required if path.endswith("generation_ledger.yml")), "")
    if not ledger_path:
        return None
    path = _resolve_path(root, ledger_path)
    if not path.exists():
        return None
    ledger = _read_yaml(path)
    ledger_status = str(ledger.get("status") or "")
    if ledger_status in {"completed", "completed_text_handoff"}:
        return None
    stderr_excerpt = str(ledger.get("stderr_excerpt") or "")
    settings_fetch_failed = bool(ledger.get("settings_fetch_failed")) or "Settings fetch failed" in stderr_excerpt
    transport_failure = bool(ledger.get("transport_failure_marker_present"))
    auth_failure = bool(ledger.get("auth_failure_marker_present"))
    adapter_kind = ledger.get("adapter_kind")
    observed_status = ledger_status or "unknown"
    legacy_status = None
    if adapter_kind in LOCAL_GROK_CLI_ADAPTERS and observed_status == "provider_timeout":
        legacy_status = observed_status
        observed_status = "local_cli_timeout"
    elif adapter_kind in LOCAL_GROK_CLI_ADAPTERS and observed_status == "provider_error":
        legacy_status = observed_status
        observed_status = "local_cli_error"
    block_reason = ledger.get("block_reason") or ledger.get("stderr_excerpt") or "media live smoke did not complete"
    if adapter_kind in LOCAL_GROK_CLI_ADAPTERS and block_reason == "grok_cli_oauth_timeout":
        block_reason = "grok_cli_timeout"
    observed = {
        "path": str(path),
        "status": observed_status,
        "backend": ledger.get("backend"),
        "adapter_kind": adapter_kind,
        "error": (
            "grok_cli_transport_or_proxy_failed"
            if transport_failure
            else "grok_cli_auth_session_unhealthy"
            if auth_failure and not settings_fetch_failed
            else
            "grok_cli_settings_fetch_failed"
            if settings_fetch_failed
            else block_reason
        ),
        "returncode": ledger.get("returncode"),
        "timeout_seconds": ledger.get("timeout_seconds"),
    }
    observed = _without_none_values(observed)
    if legacy_status:
        observed["legacy_status"] = legacy_status
    if stderr_excerpt:
        observed["stderr_excerpt"] = stderr_excerpt
    if settings_fetch_failed:
        observed["settings_fetch_failed"] = True
    if transport_failure:
        observed["transport_failure_marker_present"] = True
    if auth_failure:
        observed["auth_failure_marker_present"] = True
    backend = str(ledger.get("backend") or "")
    executed_args = _payload_plan_args(path)
    current_args = _current_backend_args(root, backend) if backend else []
    executed_shape = _command_shape(executed_args)
    current_shape = _command_shape(current_args)
    if executed_shape:
        observed["executed_command_shape"] = executed_shape
    if current_shape:
        observed["current_command_shape"] = current_shape
        observed["current_command_available"] = _command_available(current_args)
        observed["current_command_path"] = _command_path(current_args)
    executed_max_turns = _payload_plan_max_turns(path)
    current_max_turns = _current_backend_max_turns(root, backend) if backend else None
    if executed_max_turns and current_max_turns and executed_max_turns != current_max_turns:
        observed["stale_after_contract_update"] = True
        observed["stale_reason"] = "media_backend_payload_plan_no_longer_matches_current_backend_contract"
        observed["executed_max_turns"] = executed_max_turns
        observed["current_max_turns"] = current_max_turns
    elif executed_shape and current_shape and executed_shape != current_shape:
        observed["stale_after_contract_update"] = True
        observed["stale_reason"] = "media_backend_payload_plan_no_longer_matches_current_backend_command_contract"
        observed["executed_max_turns"] = executed_max_turns
        observed["current_max_turns"] = current_max_turns
    elif executed_max_turns and current_max_turns and executed_max_turns == current_max_turns:
        observed["backend_contract_current"] = True
        observed["executed_max_turns"] = executed_max_turns
        observed["current_max_turns"] = current_max_turns
    session_smoke = _current_grok_session_smoke(root, path)
    session_health_related_failure = settings_fetch_failed or transport_failure or auth_failure
    if session_health_related_failure and ledger.get("adapter_kind") in LOCAL_GROK_CLI_ADAPTERS and session_smoke:
        observed["current_session_smoke_status"] = session_smoke.get("status")
        observed["current_session_smoke_path"] = session_smoke.get("_path")
        observed["current_session_smoke_created_at"] = session_smoke.get("created_at")
        if session_smoke.get("reason"):
            observed["current_session_smoke_reason"] = session_smoke.get("reason")
    if (
        session_health_related_failure
        and ledger.get("adapter_kind") in LOCAL_GROK_CLI_ADAPTERS
        and session_smoke
        and session_smoke.get("status") == "pass"
        and session_smoke.get("_is_newer_than_ledger")
    ):
        observed["stale_after_session_health_pass"] = True
        observed["stale_reason"] = "current_grok_cli_session_smoke_passed_after_media_ledger"
    return observed


def _pending_diagnostics(
    missing: list[str],
    observed_error: dict[str, Any] | None,
    artifact_qc: dict[str, Any] | None = None,
) -> dict[str, str]:
    if artifact_qc and artifact_qc.get("status") == "fail":
        return {
            "pending_reason": "trusted_live_artifact_qc_failed",
            "evidence_interpretation": "The trusted runner returned files, but the candidate artifact structure did not pass local QC.",
            "next_action": "review_returned_candidate_artifacts_or_rerun_trusted_live_command",
        }
    if observed_error and observed_error.get("stale_after_contract_update"):
        return {
            "pending_reason": "stale_live_evidence_after_backend_contract_update",
            "evidence_interpretation": (
                "The previous media ledger was produced with an older backend command contract "
                "and must not be treated as current Grok CLI availability evidence."
            ),
            "next_action": "rerun_trusted_media_smoke_with_current_backend_contract",
        }
    if observed_error and observed_error.get("stale_after_session_health_pass"):
        if _is_agy_localhost_bind_denied(observed_error):
            return {
                "pending_reason": "historical_frontdesk_sandbox_agy_localhost_bind_denied",
                "evidence_interpretation": (
                    "The previous Writer error came from an older AGY invocation. Its session smoke "
                    "is historical evidence only and does not establish current AGY Writer health."
                ),
                "next_action": "regenerate_trusted_writer_request_for_agy_then_rerun_trusted_writer_smoke",
            }
        return {
            "pending_reason": "media_live_artifacts_not_rerun_after_grok_session_pass",
            "evidence_interpretation": (
                "The previous media ledger has a Grok CLI session, transport, or auth failure, but the current "
                "non-private Grok CLI session smoke now passes; this old ledger is no longer "
                "current Grok session-health evidence."
            ),
            "next_action": "rerun_trusted_media_smoke_with_current_grok_session",
        }
    if observed_error and observed_error.get("transport_failure_marker_present"):
        return {
            "pending_reason": "grok_cli_transport_or_proxy_failed_in_live_smoke",
            "evidence_interpretation": (
                "The previous media smoke reached the local Grok CLI command, but the run exposed "
                "a transport/network/proxy failure before returning candidate artifacts."
            ),
            "next_action": "fix_local_network_or_proxy_for_grok_cli_then_rerun_trusted_media_smoke",
        }
    if observed_error and observed_error.get("settings_fetch_failed"):
        return {
            "pending_reason": "grok_cli_settings_fetch_failed_in_live_smoke",
            "evidence_interpretation": (
                "The previous media smoke reached the local Grok CLI command, but that run did not "
                "return candidate artifacts because Grok settings fetch failed."
            ),
            "next_action": "rerun_same_agentlab_command_from_user_terminal_with_local_grok_session",
        }
    if (
        observed_error
        and observed_error.get("provider") == "agentlab-cli-executor"
        and observed_error.get("model") == "agy"
        and str(observed_error.get("error") or "").startswith("CLI agent exited")
    ):
        error_text = str(observed_error.get("error") or "")
        if "listen tcp 127.0.0.1:0" in error_text and "operation not permitted" in error_text:
            return {
                "pending_reason": "historical_frontdesk_sandbox_agy_localhost_bind_denied",
                "evidence_interpretation": (
                    "The AGY Writer route reached its CLI, but the Codex/frontdesk sandbox "
                    "denied the local language-server bind. This is historical evidence and does "
                    "not establish current AGY Writer health."
                ),
                "next_action": "regenerate_trusted_writer_request_for_agy_then_rerun_trusted_writer_smoke",
            }
        return {
            "pending_reason": "historical_writer_role_session_agy_cli_exit",
            "evidence_interpretation": (
                "The AGY Writer route exited before returning the required narrative "
                "candidate artifacts. This remains historical error evidence only."
            ),
            "next_action": "regenerate_trusted_writer_request_for_agy_then_rerun_trusted_writer_smoke",
        }
    if observed_error and missing:
        return {
            "pending_reason": "observed_error_and_missing_candidate_artifacts",
            "evidence_interpretation": "The live command started but did not return the required candidate artifacts.",
            "next_action": "rerun_or_resume_trusted_live_command_after_fixing_the_reported_agent_error",
        }
    if observed_error:
        return {
            "pending_reason": "live_ledger_or_error_report_is_not_pass",
            "evidence_interpretation": "Required files exist, but the live execution ledger reports a non-pass status.",
            "next_action": "rerun_trusted_live_command_or_review_the_non_pass_ledger",
        }
    if missing:
        return {
            "pending_reason": "missing_candidate_artifacts",
            "evidence_interpretation": "The trusted runner has not returned all required candidate artifacts.",
            "next_action": "run_trusted_live_command_and_collect_required_artifacts",
        }
    return {}


def _missing_candidate_session_health_diagnostics(
    root: Path,
    item: dict[str, Any],
    expected: dict[str, Any],
    missing: list[str],
) -> dict[str, Any]:
    if not missing:
        return {}
    expected_type = str(expected.get("type") or "")
    if (
        expected_type != "narrative_live_smoke"
        or item.get("id") != "run_crown_internal_writer_eval"
    ):
        return {}
    session_probe = _current_agy_writer_session_probe(root)
    if session_probe and session_probe.get("status") == "pass":
        return {}
    return {
        "pending_reason": "agy_writer_session_health_blocked_before_private_writer_smoke",
        "evidence_interpretation": (
            "The trusted runner has not returned Writer artifacts because the pre-run "
            "non-private AGY Writer contract probe is missing or blocked; "
            "the generated runner will not send private Crown context until this passes."
        ),
        "next_action": "rerun_agy_writer_contract_probe_from_trusted_runtime_then_run_trusted_writer_smoke",
        "session_health_gate": {
            "id": "current_agy_writer_session_health",
            "status": session_probe.get("status") if session_probe else "missing",
            "reason": (
                session_probe.get("reason")
                if session_probe
                else "agy_writer_session_probe_missing"
            ),
            "session_probe_path": session_probe.get("_path") if session_probe else None,
            "command_available": session_probe.get("installed") if session_probe else None,
            "exit_code": session_probe.get("exit_code") if session_probe else None,
            "error_class": session_probe.get("error_class") if session_probe else None,
        },
    }


def _stale_item_summary(item: dict[str, Any]) -> dict[str, Any]:
    observed = item.get("observed_error", {}) if isinstance(item.get("observed_error"), dict) else {}
    summary = _without_none_values({
        "id": item.get("id"),
        "stale_reason": observed.get("stale_reason"),
        "executed_max_turns": observed.get("executed_max_turns"),
        "current_max_turns": observed.get("current_max_turns"),
        "next_action": item.get("next_action"),
    })
    if observed.get("current_session_smoke_status"):
        summary["current_session_smoke_status"] = observed.get("current_session_smoke_status")
        summary["current_session_smoke_path"] = observed.get("current_session_smoke_path")
    return summary


def build_trusted_live_runner_status(root: Path, request_path: Path | None = None) -> dict[str, Any]:
    """Inspect request expected outputs without executing live commands."""
    root = root.resolve()
    request_path = request_path or (
        root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_request.yml"
    )
    if not request_path.is_absolute():
        request_path = root / request_path
    request = _read_yaml(request_path)
    items: list[dict[str, Any]] = []
    for item in request.get("items", []) if isinstance(request.get("items"), list) else []:
        expected = item.get("expected_outputs") if isinstance(item.get("expected_outputs"), dict) else {}
        required = [str(path) for path in expected.get("required_files", []) if path]
        missing = [path for path in required if not _path_exists(root, path)]
        observed_error = _observed_error(root, expected)
        if not observed_error:
            observed_error = _ledger_observed_error(root, required)
        artifact_qc = None
        if required and not missing and not observed_error:
            artifact_qc = _artifact_qc(root, expected, required)
        qc_failed = bool(artifact_qc and artifact_qc.get("status") == "fail")
        status_value = "pass" if required and not missing and not observed_error and not qc_failed else "pending"
        acceptance_blocker = trusted_live_acceptance_blocker(
            missing=missing,
            observed_error=observed_error,
            artifact_qc=artifact_qc,
            status=status_value,
        )
        status_item = {
            "id": item.get("id"),
            "expected_type": expected.get("type"),
            "status": status_value,
            "required_files": required,
            "missing": missing,
            "required_files_exist": not bool(missing),
            "returned_candidate_artifacts_accepted": status_value == "pass",
            "acceptance_blocker": acceptance_blocker,
            "command": item.get("command"),
        }
        if observed_error:
            status_item["observed_error"] = observed_error
            cli_contract_health = _cli_contract_health(observed_error)
            if cli_contract_health:
                status_item["cli_contract_health"] = cli_contract_health
        if artifact_qc:
            status_item["artifact_qc"] = artifact_qc
        if status_item["status"] != "pass":
            status_item.update(_pending_diagnostics(missing, observed_error, artifact_qc))
            if not observed_error:
                status_item.update(
                    _missing_candidate_session_health_diagnostics(root, item, expected, missing)
                )
        items.append(status_item)
    missing_items = [item for item in items if item["status"] != "pass"]
    stale_items = [
        item
        for item in missing_items
        if isinstance(item.get("observed_error"), dict)
        and (
            item["observed_error"].get("stale_after_contract_update")
            or item["observed_error"].get("stale_after_session_health_pass")
        )
    ]
    qc_failed_items = [
        item
        for item in missing_items
        if isinstance(item.get("artifact_qc"), dict)
        and item["artifact_qc"].get("status") == "fail"
    ]
    issues: list[str] = []
    if request.get("status") != "ready_for_trusted_runner":
        issues.append("trusted_live_runner_request_not_ready")
    if len(items) < 2:
        issues.append("expected_writer_and_media_status_items")
    return {
        "schema_version": 1,
        "report_type": "agentlab_trusted_live_runner_status",
        "root": str(root),
        "request_path": str(request_path),
        "request_id": request.get("request_id"),
        "status": "pass" if not missing_items and not issues else "pending",
        "items": items,
        "missing_items": [{"id": item["id"], "missing": item["missing"]} for item in missing_items],
        "stale_items": [
            _stale_item_summary(item)
            for item in stale_items
        ],
        "artifact_qc_failures": [
            {
                "id": item.get("id"),
                "failed_checks": [
                    check.get("id")
                    for check in item.get("artifact_qc", {}).get("checks", [])
                    if isinstance(check, dict) and check.get("status") == "fail"
                ],
                "next_action": item.get("next_action"),
            }
            for item in qc_failed_items
        ],
        "issues": issues,
        "notes": [
            "This status check does not execute live commands.",
            "pending means the trusted runner has not yet returned all expected candidate artifacts.",
            "stale_items means older failure evidence no longer matches the current backend command contract or session health.",
            "artifact_qc_failures means files returned, but local structural QC rejected the candidate.",
        ],
    }


def write_trusted_live_runner_status(root: Path, out: Path, request_path: Path | None = None) -> dict[str, Any]:
    report = build_trusted_live_runner_status(root, request_path=request_path)
    write_report_yaml(out, report, root)
    return report
