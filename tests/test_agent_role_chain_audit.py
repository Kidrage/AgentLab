from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml
from typer.testing import CliRunner

from agent_runtime.agent_role_chain_audit import build_agent_role_chain_audit
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_agent_role_chain_audit_covers_roles_workers_and_chains(tmp_path: Path) -> None:
    report = build_agent_role_chain_audit(ROOT)
    roles = {item["role"]: item for item in report["roles"]}
    chains = {item["scenario_id"]: item for item in report["production_chains"]}
    profile_contracts = {
        (item["mode"], item["tier"], item["role_key"]): item
        for item in report["profile_contracts"]
    }

    assert report["status"] == "pass"
    assert roles["Coder"]["allowed_workers"]
    assert roles["Reviewer"]["status"] == "pass"
    assert roles["Scribe"]["status"] == "pass"
    assert "qwen" in roles["Reviewer"]["allowed_workers"]
    assert "codex" in roles["Scribe"]["allowed_workers"]
    assert chains["narrative_heavy_audit"]["agents"] == [
        "Supervisor",
        "Reviewer",
        "Scribe",
        "Verifier",
    ]
    assert chains["narrative_heavy_audit"]["status"] == "pass"
    assert chains["narrative_heavy_audit"]["agent_lifecycle_coverage"]["status"] == "pass"
    assert chains["narrative_heavy_audit"]["agent_lifecycle_coverage"]["coverage"]["Reviewer"] == [
        "FICTION_REVIEW"
    ]
    assert chains["narrative_heavy_audit"]["agent_lifecycle_coverage"]["coverage"]["Scribe"] == [
        "SCRIBE_LEDGER"
    ]
    assert chains["media_series_production"]["agent_lifecycle_coverage"]["coverage"]["ArtifactProducer"] == [
        "ARTIFACT_PRODUCTION"
    ]
    artifact_profile = profile_contracts[("full_cli", "performance", "artifact_producer")]
    assert artifact_profile["status"] == "pass"
    assert artifact_profile["cli_agent"] == "codex"
    assert artifact_profile["default_model"] == "codex_gpt_5_6_sol_medium_cli_oauth"
    assert artifact_profile["default_model_catalog_status"] == "pass"
    assert artifact_profile["invocation_contract"] == "codex"
    assert artifact_profile["contract_worker"] == "codex"
    assert artifact_profile["role_binding_status"] == "pass"
    assert "role_binding_issue" not in artifact_profile
    low_artifact_profile = profile_contracts[("full_cli", "low", "artifact_producer")]
    assert low_artifact_profile["cli_agent"] == "codex"
    assert (
        low_artifact_profile["default_model"]
        == "codex_gpt_5_6_sol_medium_cli_oauth"
    )
    assert "fallback_model" not in low_artifact_profile
    assert all(
        item.get("role_binding_status") != "pass" or "role_binding_issue" not in item
        for item in report["profile_contracts"]
    )
    assert all(
        item.get("fallback_role_binding_status") != "pass" or "fallback_role_binding_issue" not in item
        for item in report["profile_contracts"]
    )
    assert any(
        "cli_agent and fallback_cli_agent must match" in invariant
        for invariant in report["invariants"]
    )
    assert any(
        "selected by runtime profiles must be allowed by role bindings" in invariant
        for invariant in report["invariants"]
    )
    assert any(
        "effective fallback model selected by runtime profiles must exist in model_catalog.yml" in invariant
        for invariant in report["invariants"]
    )
    assert any(
        "effective lifecycle node" in invariant
        for invariant in report["invariants"]
    )
    assert report["issues"] == []
    out = tmp_path / "agent_role_chain_audit.yml"

    with patch(
        "agent_role_chain_audit.build_agent_role_chain_audit",
        return_value=report,
    ):
        result = runner.invoke(app, ["agent-role-chain-audit", "--out", str(out)])

    assert result.exit_code == 0
    written = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert written["report_type"] == "agentlab_agent_role_chain_audit"
    assert written["status"] == "pass"
    assert written["profile_contracts"]
