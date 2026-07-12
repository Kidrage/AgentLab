from __future__ import annotations

import sys
from pathlib import Path

import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))
runner = CliRunner()

from atomic_io import atomic_write_yaml  # noqa: E402
from production_pack_registry import audit_pack_catalog, promote_pack_candidate, validate_pack_candidate  # noqa: E402
from run_task import app  # noqa: E402


def _catalog(path: Path) -> None:
    atomic_write_yaml(
        path,
        {
            "schema_version": 1,
            "core_runtime": ["task_run_state", "artifact_contract"],
            "pack_synthesis_policy": {"enabled": True},
            "packs": [],
        },
    )


def _valid_proposal(path: Path, pack_id: str = "installation_show_control") -> None:
    resource_contract = {
        "resource_discovery_required": True,
        "allowed_sources": [
            "user_provided_files",
            "configured_local_tools",
            "registered_role_workers",
            "approved_external_research",
        ],
        "authority_boundary": "external research can inform candidate proposals but never becomes authoritative memory",
        "external_research_requires_approval": True,
        "external_research_outputs": ["source_notes", "resource_evidence_ledger"],
        "external_research_may_not_write_project_memory": True,
        "evidence_to_memory_promotion_requires_review": True,
        "prefer_internal_workers": True,
        "new_provider_requires_approval": True,
    }
    pack = {
        "pack_id": pack_id,
        "name": "Installation Show Control",
        "description": "Governed production pack for long-running immersive installation show-control artifacts.",
        "routes": ["artifact_production_task"],
        "project_types": ["immersive_installation_project"],
        "task_domains": ["installation_art"],
        "artifact_types": ["show_control_package"],
        "lifecycle_nodes": [
            "INIT_TASK",
            "CONTEXT_PROFILE",
            "CONTEXT_BUDGET",
            "CONTEXT_PACK",
            "PREPARE_PLAN",
            "SUPERVISOR_PLAN",
            "ARTIFACT_PRODUCTION",
            "VERIFY",
            "SELF_CHECK",
            "FINALIZE",
        ],
        "domain_phases": ["cue_breakdown", "state_registry", "show_control_package"],
        "required_outputs": [
            "cue_sheet.yml",
            "state_registry.yml",
            "show_control_delivery_receipt.yml",
        ],
        "memory_contract": ["cue_sheet", "state_registry", "revision_log"],
        "resource_contract": resource_contract,
        "quality_gates": ["cue_consistency", "state_registry_written"],
    }
    atomic_write_yaml(
        path,
        {
            "schema_version": 1,
            "status": "candidate",
            "pack": pack,
        },
    )
    atomic_write_yaml(
        path.parent / "domain_memory_contract.yml",
        {
            "schema_version": 1,
            "status": "candidate",
            "memory_contract": pack["memory_contract"],
            "resource_contract": resource_contract,
            "promotion_policy": {
                "candidate_only": True,
                "auto_promote": False,
                "approval_required": "human_or_supervisor_approval",
            },
        },
    )
    atomic_write_yaml(
        path.parent / "lifecycle_profile.yml",
        {
            "schema_version": 1,
            "status": "candidate",
            "lifecycle_nodes": pack["lifecycle_nodes"],
            "quality_gates": pack["quality_gates"],
            "approval_gate": "user_or_supervisor_approval_before_pack_promotion",
        },
    )


def test_empty_synthesis_artifact_is_not_promotable(tmp_path: Path) -> None:
    proposal = tmp_path / "production_pack_proposal.yml"
    catalog = tmp_path / "production_packs.yml"
    _catalog(catalog)
    atomic_write_yaml(
        proposal,
        {
            "schema_version": 1,
            "production_pack": "pack_synthesis_candidate",
            "status": "candidate",
            "items": [],
        },
    )

    result = validate_pack_candidate(proposal, catalog)

    assert result.valid is False
    assert "proposal must contain a top-level pack mapping or pack_id fields" in result.issues


def test_promote_valid_pack_candidate_appends_to_catalog(tmp_path: Path) -> None:
    proposal = tmp_path / "production_pack_proposal.yml"
    catalog = tmp_path / "production_packs.yml"
    _catalog(catalog)
    _valid_proposal(proposal)

    result = promote_pack_candidate(proposal, catalog, approved_by="pytest")

    assert result["status"] == "promoted"
    data = yaml.safe_load(catalog.read_text(encoding="utf-8"))
    packs = data["packs"]
    assert [pack["pack_id"] for pack in packs] == ["installation_show_control"]
    assert packs[0]["generated_from"]["approved_by"] == "pytest"


def test_pack_candidate_requires_memory_and_lifecycle_companion_files(tmp_path: Path) -> None:
    proposal = tmp_path / "production_pack_proposal.yml"
    catalog = tmp_path / "production_packs.yml"
    _catalog(catalog)
    _valid_proposal(proposal)
    (tmp_path / "domain_memory_contract.yml").unlink()
    (tmp_path / "lifecycle_profile.yml").unlink()

    result = validate_pack_candidate(proposal, catalog)

    assert result.valid is False
    assert "domain_memory_contract.yml is required and must be a YAML mapping" in result.issues
    assert "lifecycle_profile.yml is required and must be a YAML mapping" in result.issues


def test_non_code_pack_requires_resource_contract(tmp_path: Path) -> None:
    proposal = tmp_path / "production_pack_proposal.yml"
    catalog = tmp_path / "production_packs.yml"
    _catalog(catalog)
    _valid_proposal(proposal, pack_id="resource_less_pack")
    data = yaml.safe_load(proposal.read_text(encoding="utf-8"))
    del data["pack"]["resource_contract"]
    atomic_write_yaml(proposal, data)

    result = validate_pack_candidate(proposal, catalog)

    assert result.valid is False
    assert "non-code production pack must define resource_contract" in result.issues


def test_non_code_pack_rejects_external_research_without_memory_boundary(tmp_path: Path) -> None:
    proposal = tmp_path / "production_pack_proposal.yml"
    catalog = tmp_path / "production_packs.yml"
    _catalog(catalog)
    _valid_proposal(proposal, pack_id="unsafe_resource_pack")
    data = yaml.safe_load(proposal.read_text(encoding="utf-8"))
    data["pack"]["resource_contract"]["external_research_may_not_write_project_memory"] = False
    data["pack"]["resource_contract"]["external_research_outputs"] = ["source_notes"]
    atomic_write_yaml(proposal, data)
    memory = yaml.safe_load((tmp_path / "domain_memory_contract.yml").read_text(encoding="utf-8"))
    del memory["resource_contract"]
    atomic_write_yaml(tmp_path / "domain_memory_contract.yml", memory)

    result = validate_pack_candidate(proposal, catalog)

    assert result.valid is False
    assert "resource_contract.external_research_may_not_write_project_memory must be true" in result.issues
    assert "resource_contract.external_research_outputs must include resource_evidence_ledger" in result.issues
    assert "domain_memory_contract.yml must mirror pack resource_contract for non-code packs" in result.issues


def test_duplicate_pack_id_requires_replace_flag(tmp_path: Path) -> None:
    proposal = tmp_path / "production_pack_proposal.yml"
    catalog = tmp_path / "production_packs.yml"
    _catalog(catalog)
    _valid_proposal(proposal)
    promote_pack_candidate(proposal, catalog, approved_by="pytest")

    result = validate_pack_candidate(proposal, catalog)

    assert result.valid is False
    assert "pack_id already exists in catalog: installation_show_control" in result.issues


def test_rejects_unsafe_outputs_and_unknown_lifecycle_nodes(tmp_path: Path) -> None:
    proposal = tmp_path / "production_pack_proposal.yml"
    catalog = tmp_path / "production_packs.yml"
    _catalog(catalog)
    _valid_proposal(proposal, pack_id="unsafe_installation_pack")
    data = yaml.safe_load(proposal.read_text(encoding="utf-8"))
    data["pack"]["lifecycle_nodes"].append("UNKNOWN_NODE")
    data["pack"]["required_outputs"].append("../escape.yml")
    atomic_write_yaml(proposal, data)

    result = validate_pack_candidate(proposal, catalog)

    assert result.valid is False
    assert "unknown lifecycle_nodes: UNKNOWN_NODE" in result.issues
    assert "required_outputs contains unsafe path: ../escape.yml" in result.issues


def test_rejects_code_shell_lifecycle_and_outputs_for_non_code_pack(tmp_path: Path) -> None:
    proposal = tmp_path / "production_pack_proposal.yml"
    catalog = tmp_path / "production_packs.yml"
    _catalog(catalog)
    _valid_proposal(proposal, pack_id="bad_installation_pack")
    data = yaml.safe_load(proposal.read_text(encoding="utf-8"))
    data["pack"]["lifecycle_nodes"].append("CODER_IMPLEMENTATION")
    data["pack"]["required_outputs"].append("implementation_report.md")
    atomic_write_yaml(proposal, data)

    result = validate_pack_candidate(proposal, catalog)

    assert result.valid is False
    assert (
        "non-code production pack cannot include code-shell lifecycle_nodes: CODER_IMPLEMENTATION"
        in result.issues
    )
    assert (
        "non-code production pack cannot require code-shell outputs: implementation_report.md"
        in result.issues
    )


def test_explicit_code_pack_can_include_code_shell_lifecycle_and_outputs(tmp_path: Path) -> None:
    proposal = tmp_path / "production_pack_proposal.yml"
    catalog = tmp_path / "production_packs.yml"
    _catalog(catalog)
    _valid_proposal(proposal, pack_id="repository_patch_pack")
    data = yaml.safe_load(proposal.read_text(encoding="utf-8"))
    data["pack"]["name"] = "Repository Patch Pack"
    data["pack"]["description"] = "Governed production pack for codebase patch work."
    data["pack"]["routes"] = ["interface_sensitive_task"]
    data["pack"]["project_types"] = ["codebase_build_project"]
    data["pack"]["task_domains"] = ["coding"]
    data["pack"]["artifact_types"] = ["code_patch"]
    data["pack"]["lifecycle_nodes"].insert(-3, "CODER_IMPLEMENTATION")
    data["pack"]["required_outputs"].append("implementation_report.md")
    atomic_write_yaml(proposal, data)
    lifecycle = yaml.safe_load((tmp_path / "lifecycle_profile.yml").read_text(encoding="utf-8"))
    lifecycle["lifecycle_nodes"] = data["pack"]["lifecycle_nodes"]
    atomic_write_yaml(tmp_path / "lifecycle_profile.yml", lifecycle)

    result = validate_pack_candidate(proposal, catalog)

    assert result.valid is True
    assert result.issues == []


def test_pack_catalog_audit_flags_equal_specificity_route_collision(tmp_path: Path) -> None:
    catalog = tmp_path / "production_packs.yml"
    atomic_write_yaml(
        catalog,
        {
            "schema_version": 1,
            "packs": [
                {
                    "pack_id": "article_a",
                    "routes": ["article_light_draft"],
                    "lifecycle_nodes": ["INIT_TASK", "PREPARE_PLAN", "SUPERVISOR_PLAN", "FINALIZE"],
                },
                {
                    "pack_id": "article_b",
                    "routes": ["article_light_draft"],
                    "lifecycle_nodes": ["INIT_TASK", "PREPARE_PLAN", "SUPERVISOR_PLAN", "FINALIZE"],
                },
            ],
        },
    )

    report = audit_pack_catalog(catalog)

    assert report["status"] == "fail"
    assert report["issues"] == [
        "ambiguous selector collision on route article_light_draft: article_a and article_b have equal specificity"
    ]
    assert report["selector_overlaps"][0]["status"] == "ambiguous_equal_specificity"


def test_pack_catalog_audit_allows_disambiguated_route_overlap() -> None:
    report = audit_pack_catalog(ROOT / "config" / "production_packs.yml")
    media_overlap = next(
        item
        for item in report["selector_overlaps"]
        if item["route"] == "media_generation_task"
        and set(item["pack_ids"]) == {"media_series_production", "media_generation"}
    )

    assert report["status"] == "pass"
    assert report["issues"] == []
    assert report["route_reference_audit"]["status"] == "pass"
    assert report["route_reference_audit"]["known_route_count"] > 0
    assert media_overlap["status"] == "selector_disjoint"
    assert media_overlap["disambiguated_by"] == ["project_types"]


def test_pack_catalog_audit_flags_unknown_pack_route(tmp_path: Path) -> None:
    catalog = tmp_path / "production_packs.yml"
    routing = tmp_path / "routing_rules.yml"
    atomic_write_yaml(
        catalog,
        {
            "schema_version": 1,
            "packs": [
                {
                    "pack_id": "bad_pack",
                    "routes": ["missing_route"],
                    "project_types": ["bad_project"],
                }
            ],
        },
    )
    atomic_write_yaml(routing, {"routes": {"known_route": {"agents": ["Supervisor"]}}})

    report = audit_pack_catalog(catalog, routing)

    assert report["status"] == "fail"
    assert "pack bad_pack references unknown route: missing_route" in report["issues"]
    assert report["route_reference_audit"]["status"] == "fail"


def test_pack_catalog_audit_flags_domain_route_mismatch(tmp_path: Path) -> None:
    catalog = tmp_path / "production_packs.yml"
    routing = tmp_path / "routing_rules.yml"
    domain_routes = tmp_path / "domain_route_packs.yml"
    atomic_write_yaml(catalog, {"schema_version": 1, "packs": []})
    atomic_write_yaml(
        routing,
        {
            "routes": {
                "article_light_draft": {"agents": ["Supervisor", "ArtifactProducer"]},
                "narrative_light_chapter": {"agents": ["Supervisor", "Writer"]},
            }
        },
    )
    atomic_write_yaml(
        domain_routes,
        {
            "domain_packs": {
                "creative_writing": {
                    "recommended_route": "narrative_light_chapter",
                    "forbidden_fallback_routes": ["narrative_light_chapter"],
                    "route_proposal": {"route_key": "article_light_draft"},
                }
            }
        },
    )

    report = audit_pack_catalog(catalog, routing, domain_routes)

    assert report["status"] == "fail"
    assert (
        "domain creative_writing.recommended_route is also listed as forbidden fallback: narrative_light_chapter"
        in report["issues"]
    )
    assert (
        "domain creative_writing.route_proposal.route_key=article_light_draft does not match narrative_light_chapter"
        in report["issues"]
    )


def test_pack_catalog_audit_flags_domain_forbidden_route_exposed_by_owner_pack(tmp_path: Path) -> None:
    catalog = tmp_path / "production_packs.yml"
    routing = tmp_path / "routing_rules.yml"
    domain_routes = tmp_path / "domain_route_packs.yml"
    atomic_write_yaml(
        catalog,
        {
            "schema_version": 1,
            "packs": [
                {
                    "pack_id": "narrative_longform",
                    "routes": ["narrative_light_chapter", "fiction_chapter_pipeline"],
                    "lifecycle_nodes": ["INIT_TASK", "PREPARE_PLAN", "SUPERVISOR_PLAN", "FINALIZE"],
                }
            ],
        },
    )
    atomic_write_yaml(
        routing,
        {
            "routes": {
                "narrative_light_chapter": {"agents": ["Supervisor", "Writer"]},
                "fiction_chapter_pipeline": {"agents": ["Supervisor", "Writer", "Reviewer"]},
            }
        },
    )
    atomic_write_yaml(
        domain_routes,
        {
            "domain_packs": {
                "creative_writing": {
                    "recommended_route": "narrative_light_chapter",
                    "forbidden_fallback_routes": ["fiction_chapter_pipeline"],
                }
            }
        },
    )

    report = audit_pack_catalog(catalog, routing, domain_routes)

    assert report["status"] == "fail"
    assert (
        "domain creative_writing forbidden fallback route fiction_chapter_pipeline "
        "is still exposed by pack narrative_longform"
    ) in report["issues"]


def test_pack_candidate_cli_validate_and_promote_dry_run(tmp_path: Path) -> None:
    proposal = tmp_path / "production_pack_proposal.yml"
    catalog = tmp_path / "production_packs.yml"
    _catalog(catalog)
    _valid_proposal(proposal)

    runner = CliRunner()
    validate_result = runner.invoke(
        app,
        ["pack-candidate-validate", "--proposal", str(proposal), "--catalog", str(catalog)],
    )
    promote_result = runner.invoke(
        app,
        [
            "pack-candidate-promote",
            "--proposal",
            str(proposal),
            "--catalog",
            str(catalog),
            "--approved-by",
            "pytest",
            "--dry-run",
        ],
    )

    assert validate_result.exit_code == 0
    assert promote_result.exit_code == 0
    assert "dry_run" in promote_result.output
    assert yaml.safe_load(catalog.read_text(encoding="utf-8"))["packs"] == []


def test_pack_catalog_audit_cli_writes_yaml(tmp_path: Path) -> None:
    out = tmp_path / "pack_catalog_audit.yml"

    result = runner.invoke(app, ["pack-catalog-audit", "--out", str(out)])

    assert result.exit_code == 0
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["report_type"] == "agentlab_production_pack_catalog_audit"
    assert report["status"] == "pass"
    assert report["issues"] == []


def test_pack_catalog_audit_cli_fails_on_ambiguous_catalog(tmp_path: Path) -> None:
    catalog = tmp_path / "production_packs.yml"
    out = tmp_path / "pack_catalog_audit.yml"
    atomic_write_yaml(
        catalog,
        {
            "schema_version": 1,
            "packs": [
                {"pack_id": "article_a", "routes": ["article_light_draft"]},
                {"pack_id": "article_b", "routes": ["article_light_draft"]},
            ],
        },
    )

    result = runner.invoke(app, ["pack-catalog-audit", "--catalog", str(catalog), "--out", str(out)])

    assert result.exit_code == 1
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["status"] == "fail"
    assert report["selector_overlaps"][0]["status"] == "ambiguous_equal_specificity"
