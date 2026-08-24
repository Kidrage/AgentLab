"""Explicit fail-closed model and budget authority for narrative test roots."""

from __future__ import annotations

from pathlib import Path

import yaml


TEST_WRITER_ROUTE = "TestWriterStrict"
TEST_WRITER_MODEL = "test_writer_model"
TEST_BUDGET = "balanced"


def install_narrative_test_authority(root: Path, *, writer: str) -> dict[str, str]:
    config = Path(root) / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "model_capacity.yml").write_text(
        yaml.safe_dump(
            {
                "routes": {
                    TEST_WRITER_ROUTE: {
                        "role": "writer",
                        "worker": writer,
                        "model_key": TEST_WRITER_MODEL,
                        "invocation_contract": "test-writer/v1",
                        "pool": "test",
                        "approved_fallbacks": [],
                        "fallback_on": [],
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config / "execution_policy.yml").write_text(
        yaml.safe_dump(
            {
                "budget_mode_policy": {
                    "default_budget_mode": TEST_BUDGET,
                    "available_modes": [TEST_BUDGET],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return {
        "writer_capacity_route": TEST_WRITER_ROUTE,
        "writer_model_key": TEST_WRITER_MODEL,
        "writer_budget": TEST_BUDGET,
        "audit_budget": TEST_BUDGET,
    }


def narrative_action_config(root: Path, *, writer: str) -> dict[str, object]:
    authority = install_narrative_test_authority(root, writer=writer)
    return {
        **authority,
        "writer_worker": writer,
        "allow_writer_cli_fallback": False,
    }
