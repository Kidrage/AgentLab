from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "acceptance_runs" / "agentlab_capability_acceptance"


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
    failures = {
        path.name: _null_paths(yaml.safe_load(path.read_text(encoding="utf-8")))
        for path in sorted(ACCEPTANCE.glob("*.yml"))
    }
    assert {name: paths for name, paths in failures.items() if paths} == {}


def test_readme_route_overview_does_not_advertise_legacy_fiction_pipeline() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    route_line = next(
        line for line in readme.splitlines() if line.startswith("Route profiles / 路由配置:")
    )

    assert "fiction_chapter_pipeline" not in route_line
    for route_key in [
        "narrative_light_chapter",
        "narrative_batch_chapters",
        "narrative_heavy_audit",
        "article_light_draft",
        "media_generation_task",
    ]:
        assert route_key in route_line


def test_acceptance_docs_reference_authority_without_copying_live_snapshot() -> None:
    current = _read_yaml(ACCEPTANCE / "current.yml")
    operating = (ROOT / "docs" / "AGENTLAB_OPERATING_LOGIC.zh-CN.md").read_text(
        encoding="utf-8"
    )
    matrix = (ROOT / "docs" / "AGENTLAB_CAPABILITY_ACCEPTANCE_MATRIX.md").read_text(
        encoding="utf-8"
    )
    operating_model = (ROOT / "OPERATING_MODEL.md").read_text(encoding="utf-8")
    combined = "\n".join([operating, matrix, operating_model])

    canonical_path = "acceptance_runs/agentlab_capability_acceptance/current.yml"
    assert canonical_path in combined
    assert "internal_live_readiness.yml" in matrix
    assert "external_acceptance_readiness.yml" in operating + matrix
    assert f"overall_status: {current['overall_status']}" not in combined
    for volatile_field in [
        "selected_ready=",
        "selected_blocked=",
        "required_files_missing_count:",
        "returned_candidate_artifacts_accepted_count:",
        "stale_private_selected_command_hit_count:",
    ]:
        assert volatile_field not in combined


def test_readiness_compatibility_report_declares_its_canonical_source() -> None:
    internal = _read_yaml(ACCEPTANCE / "internal_live_readiness.yml")
    legacy = _read_yaml(ACCEPTANCE / "external_acceptance_readiness.yml")

    assert internal["report_type"] == "agentlab_internal_live_readiness"
    assert legacy["report_type"] == internal["report_type"]
    assert legacy["canonical_report_type"] == internal["report_type"]


def test_pack_synthesis_resource_boundary_is_machine_readable() -> None:
    synthesis = _read_yaml(ACCEPTANCE / "production_pack_synthesis_smoke.yml")
    resource_contract = synthesis["validated_candidate_pack"]["resource_contract"]

    assert "approved_external_research" in resource_contract["allowed_sources"]
    assert resource_contract["external_research_requires_approval"] is True
    assert resource_contract["external_research_may_not_write_project_memory"] is True
    assert "resource_evidence_ledger" in resource_contract["external_research_outputs"]
    passed = {
        check["id"]
        for check in synthesis["semantic_checks"]
        if check.get("status") == "pass"
    }
    assert {
        "research_brief_external_resource_boundary",
        "proposal_external_resource_boundary",
    } <= passed


def test_legacy_private_handoff_points_to_canonical_role_session_handoff() -> None:
    canonical = (ACCEPTANCE / "role_session_acceptance_handoff.md").read_text(
        encoding="utf-8"
    )
    legacy = (ACCEPTANCE / "private_live_smoke_approval_handoff.md").read_text(
        encoding="utf-8"
    )

    assert "Canonical term: `private_role_session_acceptance_smoke`" in canonical
    assert "AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1" in canonical
    assert "Legacy path:" in legacy
    assert "role_session_acceptance_handoff.md" in legacy
