from __future__ import annotations

import csv
from pathlib import Path
import sys
from types import SimpleNamespace

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

    assert rows[("full", "supervisor")]["cli_agent"] == "hermes"
    assert rows[("full", "supervisor")]["model_key"] == "codex_gpt_5_5_high_hermes_oauth"
    assert rows[("full", "supervisor")]["runtime_route_id"] == "supervisor_codex"
    assert rows[("full", "supervisor")]["checkpoint_candidates"] == "supervisor_deepseek"
    assert rows[("full", "supervisor")]["capacity_route"] == ""
    assert rows[("full", "supervisor")]["fallback_routes"] == ""
    assert rows[("full", "observer")]["cli_agent"] == "agy"
    assert rows[("full", "observer")]["model_key"] == "gemini_3_5_flash_high_agy_oauth"
    assert rows[("full", "observer")]["runtime_route_id"] == "observer_gemini"
    assert rows[("full", "observer")]["checkpoint_candidates"] == "observer_claude"
    assert rows[("full", "writer")]["cli_agent"] == "claude_code"
    assert rows[("full", "writer")]["model_key"] == "deepseek_v4_pro"
    assert rows[("full", "writer")]["runtime_route_id"] == "writer_pro"
    assert rows[("full", "writer")]["checkpoint_candidates"] == "writer_flash"
    assert rows[("full", "researcher")]["cli_agent"] == "agy"
    assert rows[("full", "researcher")]["model_key"] == "gemini_3_5_flash_high_agy_oauth"
    assert rows[("full", "artifact_producer")]["cli_agent"] == "claude_code"
    assert rows[("full", "artifact_producer")]["invocation_contract"] == "claude"
    assert rows[("full", "artifact_producer")]["artifact_types"] == (
        "text | image | video | audio | spreadsheet | presentation | mixed"
    )
    artifact_dispatch = rows[("full", "artifact_producer")]["artifact_dispatch"]
    assert (
        "text|spreadsheet|presentation=>"
        "claude_deepseek/claude_code/claude/deepseek_api"
    ) in artifact_dispatch
    assert "image|video|audio|mixed=>unsupported" in artifact_dispatch
    assert "deepseek_api" in rows[("low", "artifact_producer")][
        "artifact_dispatch"
    ]
    for tier in ("full", "performance", "low"):
        assert rows[(tier, "reviewer")]["cli_agent"] == "claude_code"
        assert rows[(tier, "visual_reviewer")]["cli_agent"] == "agy"
        assert rows[(tier, "visual_reviewer")]["role"] == "Reviewer"
        assert rows[(tier, "scribe")]["cli_agent"] == "claude_code"
        assert rows[(tier, "narrative_planner")]["cli_agent"] == "claude_code"
        assert rows[(tier, "reviewer")]["role_binding_status"] == "ok"
        assert rows[(tier, "visual_reviewer")]["role_binding_status"] == "ok"
        assert rows[(tier, "scribe")]["role_binding_status"] == "ok"
    assert all(row["role_binding_status"] in {"ok", "not_applicable"} for row in full_cli)
    assert rows[("low", "writer")]["runtime_route_id"] == "writer_flash"
    assert rows[("low", "writer")]["checkpoint_candidates"] == "writer_pro"
    assert rows[("low", "writer")]["capacity_route"] == ""
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


def test_heavy_audit_alias_roles_resolve_to_bound_cli_workers() -> None:
    for budget_mode in ("max_quality", "balanced", "frugal"):
        plan = SimpleNamespace(budget_mode=budget_mode)
        for role in ("Reviewer", "Scribe", "NarrativePlanner"):
            preview = resolve_agent_execution_preview(ROOT, plan, role)
            assert preview["executor_type"] == "cli_agent"
            assert preview["cli_agent"] == "claude_code"
            assert preview["role_binding_allowed"] is True
