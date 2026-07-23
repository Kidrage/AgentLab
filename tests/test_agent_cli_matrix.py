from __future__ import annotations

import csv
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest
import yaml

from scripts.generate_agent_cli_matrix import build_matrices, generate


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runner import resolve_agent_execution_preview  # noqa: E402


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_matrix_references_are_valid_and_full_cli_full_matches_required_defaults() -> None:
    full_cli, cli = build_matrices(ROOT)
    rows = {(row["tier"], row["profile_key"]): row for row in full_cli}

    assert rows[("full", "supervisor")]["cli_agent"] == "codex"
    assert rows[("full", "supervisor")]["model_key"] == "codex_gpt_5_6_sol_xhigh_cli_oauth"
    assert rows[("full", "supervisor")]["capacity_route"] == "Supervisor"
    assert rows[("full", "supervisor")]["fallback_routes"] == "SupervisorDeepSeek"
    assert rows[("full", "supervisor")]["fallback_cli_agent"] == "claude_code"
    assert rows[("full", "supervisor")]["fallback_model_key"] == "deepseek_v4_pro"
    assert rows[("full", "observer")]["cli_agent"] == "agy"
    assert rows[("full", "observer")]["model_key"] == "gemini_3_5_flash_high_agy_oauth"
    assert rows[("full", "observer")]["capacity_route"] == "Observer"
    assert rows[("full", "observer")]["fallback_routes"] == "ObserverClaude"
    assert rows[("full", "observer")]["fallback_cli_agent"] == "agy"
    assert rows[("full", "observer")]["fallback_model_key"] == "claude_sonnet_4_6_agy_oauth"
    assert rows[("full", "writer")]["cli_agent"] == "claude_code"
    assert rows[("full", "writer")]["model_key"] == "deepseek_v4_pro"
    assert rows[("full", "writer")]["capacity_route"] == "Writer"
    assert rows[("full", "writer")]["fallback_routes"] == "WriterFlash"
    assert rows[("full", "writer")]["fallback_cli_agent"] == "claude_code"
    assert rows[("full", "writer")]["fallback_model_key"] == "deepseek_v4_flash"
    assert rows[("full", "researcher")]["cli_agent"] == "grok"
    assert rows[("full", "artifact_producer")]["invocation_contract"] == "grok_media"
    assert rows[("full", "artifact_producer")]["artifact_types"] == (
        "text | image | video | audio | spreadsheet | presentation | mixed"
    )
    artifact_dispatch = rows[("full", "artifact_producer")]["artifact_dispatch"]
    assert (
        "text|spreadsheet|presentation=>"
        "qwen_cli/qwen/qwen_artifact/ArtifactProducerQwenMax"
    ) in artifact_dispatch
    assert "image|video=>grok_media/grok/grok_media/ArtifactProducer" in artifact_dispatch
    assert "audio|mixed=>unsupported" in artifact_dispatch
    assert "ArtifactProducerQwenLow" in rows[("low", "artifact_producer")][
        "artifact_dispatch"
    ]
    for tier in ("full", "performance", "low"):
        assert rows[(tier, "reviewer")]["cli_agent"] == "claude_code"
        assert rows[(tier, "visual_reviewer")]["cli_agent"] == "agy"
        assert rows[(tier, "visual_reviewer")]["role"] == "Reviewer"
        assert rows[(tier, "scribe")]["cli_agent"] == "qwen"
        assert rows[(tier, "reviewer")]["role_binding_status"] == "ok"
        assert rows[(tier, "visual_reviewer")]["role_binding_status"] == "ok"
        assert rows[(tier, "scribe")]["role_binding_status"] == "ok"
    assert all(row["role_binding_status"] in {"ok", "not_applicable"} for row in full_cli)
    assert rows[("low", "writer")]["capacity_route"] == "WriterLow"
    assert rows[("low", "writer")]["fallback_routes"] == ""
    assert rows[("low", "writer")]["fallback_cli_agent"] == ""
    assert rows[("low", "writer")]["fallback_model_key"] == ""
    assert {row["component"] for row in cli} >= {"hermes", "claude_code", "codex", "qwen", "agy"}


def test_checked_in_csv_matrices_are_deterministic(tmp_path: Path) -> None:
    full_cli_out = tmp_path / "full_cli.csv"
    cli_out = tmp_path / "cli.csv"
    generate(ROOT, full_cli_out, cli_out)

    assert _read_csv(full_cli_out) == _read_csv(ROOT / "docs" / "AGENTLAB_FULL_CLI_MATRIX.csv")
    assert _read_csv(cli_out) == _read_csv(ROOT / "docs" / "AGENTLAB_CLI_REQUIREMENTS.csv")


def test_matrix_rejects_regression_of_scoped_default_performance_route(
    tmp_path: Path,
) -> None:
    shutil.copytree(ROOT / "config", tmp_path / "config")
    profiles_path = tmp_path / "config" / "agent_model_profiles.yml"
    profiles = yaml.safe_load(profiles_path.read_text(encoding="utf-8"))
    route = profiles["modes"]["full_cli"]["tiers"]["performance"]["reposcout"]
    route["cli_agent"] = "codex"
    route["invocation_contract"] = "codex"
    profiles_path.write_text(
        yaml.safe_dump(profiles, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="required default route.*claude_code"):
        build_matrices(tmp_path)


def test_matrix_rejects_foreign_provider_model_on_codex_worker(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "config", tmp_path / "config")
    profiles_path = tmp_path / "config" / "agent_model_profiles.yml"
    profiles = yaml.safe_load(profiles_path.read_text(encoding="utf-8"))
    route = profiles["modes"]["full_cli"]["tiers"]["performance"]["supervisor"]
    route["default"] = "deepseek_v4_pro"
    profiles_path.write_text(
        yaml.safe_dump(profiles, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="model provider 'deepseek_official'.*not contract command 'codex'"):
        build_matrices(tmp_path)


def test_heavy_audit_alias_roles_resolve_to_bound_cli_workers() -> None:
    for budget_mode in ("max_quality", "balanced", "frugal"):
        plan = SimpleNamespace(budget_mode=budget_mode)
        for role in ("Reviewer",):
            preview = resolve_agent_execution_preview(ROOT, plan, role)
            assert preview["executor_type"] == "cli_agent"
            assert preview["cli_agent"] == "claude_code"
            assert preview["role_binding_allowed"] is True
        scribe = resolve_agent_execution_preview(ROOT, plan, "Scribe")
        assert scribe["executor_type"] == "cli_agent"
        assert scribe["cli_agent"] == "qwen"
        assert scribe["role_binding_allowed"] is True
