from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _null_paths(value: Any, path: str = "") -> list[str]:
    if value is None:
        return [path or "<root>"]
    if isinstance(value, dict):
        paths: list[str] = []
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            paths.extend(_null_paths(item, child_path))
        return paths
    if isinstance(value, list):
        paths = []
        for index, item in enumerate(value):
            paths.extend(_null_paths(item, f"{path}[{index}]"))
        return paths
    return []


def test_current_acceptance_yaml_reports_do_not_emit_null_fields() -> None:
    report_dir = ROOT / "acceptance_runs" / "agentlab_capability_acceptance"
    failures = {
        path.name: _null_paths(yaml.safe_load(path.read_text(encoding="utf-8")))
        for path in sorted(report_dir.glob("*.yml"))
    }
    failures = {name: paths for name, paths in failures.items() if paths}

    assert failures == {}


def test_readme_route_overview_does_not_advertise_legacy_fiction_pipeline() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    route_line = next(line for line in readme.splitlines() if line.startswith("Route profiles / 路由配置:"))

    assert "fiction_chapter_pipeline" not in route_line
    for route_key in [
        "narrative_light_chapter",
        "narrative_batch_chapters",
        "narrative_heavy_audit",
        "article_light_draft",
        "media_generation_task",
    ]:
        assert route_key in route_line


def test_operator_docs_match_current_acceptance_status() -> None:
    current = _read_yaml(ROOT / "acceptance_runs" / "agentlab_capability_acceptance" / "current.yml")
    trusted_status = _read_yaml(
        ROOT / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_status.yml"
    )
    trusted_collect = _read_yaml(
        ROOT / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_collect.yml"
    )
    trusted_operator_handoff = _read_yaml(
        ROOT / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_operator_handoff.yml"
    )
    synthesis = _read_yaml(
        ROOT / "acceptance_runs" / "agentlab_capability_acceptance" / "production_pack_synthesis_smoke.yml"
    )
    hygiene = _read_yaml(
        ROOT / "acceptance_runs" / "agentlab_capability_acceptance" / "acceptance_report_hygiene.yml"
    )
    internal_readiness = _read_yaml(
        ROOT / "acceptance_runs" / "agentlab_capability_acceptance" / "internal_live_readiness.yml"
    )
    legacy_readiness = _read_yaml(
        ROOT / "acceptance_runs" / "agentlab_capability_acceptance" / "external_acceptance_readiness.yml"
    )
    operating = (ROOT / "docs" / "AGENTLAB_OPERATING_LOGIC.zh-CN.md").read_text(encoding="utf-8")
    matrix = (ROOT / "docs" / "AGENTLAB_CAPABILITY_ACCEPTANCE_MATRIX.md").read_text(encoding="utf-8")
    operating_model = (ROOT / "OPERATING_MODEL.md").read_text(encoding="utf-8")
    role_session_handoff = (
        ROOT / "acceptance_runs" / "agentlab_capability_acceptance" / "role_session_acceptance_handoff.md"
    ).read_text(encoding="utf-8")
    legacy_handoff = (
        ROOT / "acceptance_runs" / "agentlab_capability_acceptance" / "private_live_smoke_approval_handoff.md"
    ).read_text(encoding="utf-8")

    overall_status = current["overall_status"]
    status_counts = current["status_counts"]
    readiness_status = internal_readiness["status"]
    trusted_items = {
        item["id"]: item
        for item in trusted_status.get("items", [])
        if isinstance(item, dict) and item.get("id")
    }
    writer_blocker = trusted_items["run_crown_internal_writer_eval"]["acceptance_blocker"]
    media_blocker = trusted_items["run_crown_internal_media_smoke"]["acceptance_blocker"]
    current_by_id = {
        item["id"]: item
        for item in current.get("capabilities", [])
        if isinstance(item, dict) and item.get("id")
    }
    collector_issue = current_by_id["trusted_live_runner_collect"]["issues"][0]
    collector_reasons = [
        str(item)
        for item in trusted_collect.get("acceptance_blocker_reasons", [])
        if item
    ]
    selected_readiness = trusted_operator_handoff.get("selected_item_readiness", {})
    selected_ready = ",".join(selected_readiness.get("ready_item_ids", []) or []) or "none"
    selected_blocked = ",".join(selected_readiness.get("blocked_item_ids", []) or []) or "none"

    assert internal_readiness["report_type"] == "agentlab_internal_live_readiness"
    assert legacy_readiness["report_type"] == "agentlab_internal_live_readiness"
    assert legacy_readiness["canonical_report_type"] == "agentlab_internal_live_readiness"

    assert f"overall_status: {overall_status}" in operating
    for status, count in status_counts.items():
        assert f"{status}: {count}" in operating
    assert f"该报告当前是 `{readiness_status}`" in operating
    if readiness_status != "ready_for_internal_live_smoke":
        assert "该报告当前是 `ready_for_internal_live_smoke`" not in operating

    assert f"current report status is `{overall_status}`" in matrix
    assert f"`{readiness_status}`" in matrix
    assert "internal_live_readiness.yml" in matrix
    assert "internal-live-readiness" in matrix
    assert "agentlab_internal_live_readiness" in matrix
    for phrase in [
        "required_files_exist",
        "returned_candidate_artifacts_accepted",
        "acceptance_blocker",
        "full_run_requires_trusted_status_pass",
        "approval_gate_before_private_context",
        "AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1",
        "acceptance_blockers",
        "acceptance_blocker_reasons",
        "required_files_missing_count",
        "returned_candidate_artifacts_accepted_count",
        "acceptance_report_hygiene_status",
        "live_unblock_plan.yml",
        "canonical_text_artifact_count",
        "canonical_text_issues",
        "hygiene_private_selected_command_hits",
        "stale_private_selected_command_hit_count",
        "selected private role-session commands must include AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1",
        "private_role_session_acceptance_smoke",
        "selected_item_readiness",
        f"selected_ready={selected_ready}",
        f"selected_blocked={selected_blocked}",
        "hermes_frontdesk=True",
        "direct_closed_loop=True",
        "codex_external_worker=True",
        "role_session_acceptance_handoff.md",
        collector_issue,
        writer_blocker,
        media_blocker,
    ]:
        assert phrase in operating
        assert phrase in matrix
    assert "local `hermes`" in matrix
    for reason in collector_reasons:
        assert reason in operating
        assert reason in matrix
    synthesis_pack = synthesis["validated_candidate_pack"]
    resource_contract = synthesis_pack["resource_contract"]
    assert "approved_external_research" in resource_contract["allowed_sources"]
    assert resource_contract["external_research_requires_approval"] is True
    assert resource_contract["external_research_may_not_write_project_memory"] is True
    assert "resource_evidence_ledger" in resource_contract["external_research_outputs"]
    synthesis_check_ids = {check["id"] for check in synthesis["semantic_checks"] if check["status"] == "pass"}
    assert "research_brief_external_resource_boundary" in synthesis_check_ids
    assert "proposal_external_resource_boundary" in synthesis_check_ids
    for phrase in [
        "approved_external_research",
        "resource_evidence_ledger",
        "external_research_may_not_write_project_memory",
    ]:
        assert phrase in operating
        assert phrase in matrix
    assert f"required_files_missing_count: {trusted_collect['required_files_missing_count']}" in operating
    assert f"required_files_missing_count: {trusted_collect['required_files_missing_count']}" in matrix
    assert f"returned_candidate_artifacts_accepted_count: {trusted_collect['returned_candidate_artifacts_accepted_count']}" in operating
    assert f"returned_candidate_artifacts_accepted_count: {trusted_collect['returned_candidate_artifacts_accepted_count']}" in matrix
    assert trusted_collect["required_files_missing_count"] >= 0
    assert trusted_collect["returned_candidate_artifacts_accepted_count"] >= 0
    if "session health" not in collector_issue:
        assert "not session health" in matrix
        assert "不是 session health" in operating
    assert "exits nonzero unless" in matrix
    assert "非零退出" in operating
    assert "external_acceptance_readiness.yml` file is compatibility output only" in matrix
    assert "external_acceptance_readiness.yml` 只是旧消费者兼容文件" in operating
    assert "acceptance_report_hygiene.yml" in matrix
    assert "acceptance_report_hygiene.yml" in operating
    assert f"canonical_text_artifact_count: {hygiene['canonical_text_artifact_count']}" in matrix
    assert f"canonical_text_artifact_count: {hygiene['canonical_text_artifact_count']}" in operating
    assert hygiene["canonical_text_issues"] == []
    private_command_hit_count = len(hygiene["stale_private_selected_command_hits"])
    assert f"stale_private_selected_command_hit_count: {private_command_hit_count}" in matrix
    assert f"stale_private_selected_command_hit_count: {private_command_hit_count}" in operating
    assert hygiene["private_selected_command_policy"] in matrix
    assert hygiene["private_selected_command_policy"] in operating
    assert private_command_hit_count == 0
    assert "non-authoritative snapshots" in matrix
    assert "非权威快照" in operating
    assert "legacy terms are terminology-only" in matrix
    assert "旧简称" in operating
    assert "Canonical term: `private_role_session_acceptance_smoke`" in role_session_handoff
    assert "AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1" in role_session_handoff
    assert "AGENTLAB_TRUSTED_LIVE_RUNNER=1 AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1" in role_session_handoff
    assert "Legacy path:" in legacy_handoff
    assert "role_session_acceptance_handoff.md" in legacy_handoff
    assert "AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1" in legacy_handoff

    stale_primary_phrases = [
        "The external acceptance readiness audit is generated by:",
        "live external-provider blockers",
        "live external execution now requires",
        "remains blocked by missing xAI/Grok live auth",
        "hermes_grok_oauth` still has no verified live-generation adapter",
        "blocks its localhost language-server bind",
        "trusted runtime or user terminal that allows localhost bind",
        "current non-private Grok prompt contract is pass",
        "--session-health-only` 和完整/selected 私有运行都必须用 `AGENTLAB_TRUSTED_LIVE_RUNNER=1` 前缀",
    ]
    combined = "\n".join([operating, matrix, operating_model])
    compact_operating_model = " ".join(operating_model.split())
    for phrase in stale_primary_phrases:
        assert phrase not in combined

    assert "API-key auth is fallback-only" in operating_model
    assert "does not use API keys as the default unblock path" in compact_operating_model
