from __future__ import annotations

import csv
from pathlib import Path

from scripts.generate_agent_cli_matrix import build_matrices, generate


ROOT = Path(__file__).resolve().parents[1]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_matrix_references_are_valid_and_full_cli_full_matches_required_defaults() -> None:
    full_cli, cli = build_matrices(ROOT)
    rows = {(row["tier"], row["role"]): row for row in full_cli}

    assert rows[("full", "Supervisor")]["cli_agent"] == "hermes"
    assert rows[("full", "Supervisor")]["model_key"] == "codex_gpt_5_5_high_hermes_oauth"
    assert rows[("full", "Supervisor")]["fallback_cli_agent"] == "claude_code"
    assert rows[("full", "Supervisor")]["fallback_model_key"] == "deepseek_v4_pro"
    assert rows[("full", "Writer")]["cli_agent"] == "agy"
    assert rows[("full", "Writer")]["model_key"] == "gemini_3_5_flash_high_agy_oauth"
    assert all(row["role_binding_status"] in {"ok", "not_applicable"} for row in full_cli)
    assert {row["component"] for row in cli} >= {"hermes", "claude_code", "codex", "qwen", "agy"}


def test_checked_in_csv_matrices_are_deterministic(tmp_path: Path) -> None:
    full_cli_out = tmp_path / "full_cli.csv"
    cli_out = tmp_path / "cli.csv"
    generate(ROOT, full_cli_out, cli_out)

    assert _read_csv(full_cli_out) == _read_csv(ROOT / "docs" / "AGENTLAB_FULL_CLI_MATRIX.csv")
    assert _read_csv(cli_out) == _read_csv(ROOT / "docs" / "AGENTLAB_CLI_REQUIREMENTS.csv")
