from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.goal_acceptance_scope import acceptance_mode, load_goal_acceptance_scope


def test_goal_acceptance_scope_defaults_to_full_acceptance(tmp_path: Path) -> None:
    scope = load_goal_acceptance_scope(tmp_path)

    assert scope["valid"] is True
    assert scope["status"] == "legacy_default"
    assert acceptance_mode(scope, "production_pack_synthesis") == "full_role_session"
    assert acceptance_mode(scope, "media_generation") == "full_live_acceptance"


def test_goal_acceptance_scope_loads_narrowed_modes(tmp_path: Path) -> None:
    path = tmp_path / "acceptance_runs" / "agentlab_capability_acceptance" / "goal_acceptance_scope.yml"
    path.parent.mkdir(parents=True)
    path.write_text(
        yaml.safe_dump(
            {
                "scope_id": "narrowed",
                "acceptance_modes": {
                    "production_pack_synthesis": "deterministic_scaffold_only",
                    "media_generation": "readiness_only",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    scope = load_goal_acceptance_scope(tmp_path)

    assert scope["valid"] is True
    assert acceptance_mode(scope, "production_pack_synthesis") == "deterministic_scaffold_only"
    assert acceptance_mode(scope, "media_generation") == "readiness_only"


def test_goal_acceptance_scope_rejects_unknown_modes(tmp_path: Path) -> None:
    path = tmp_path / "acceptance_runs" / "agentlab_capability_acceptance" / "goal_acceptance_scope.yml"
    path.parent.mkdir(parents=True)
    path.write_text(
        yaml.safe_dump({"acceptance_modes": {"media_generation": "pretend_pass"}}),
        encoding="utf-8",
    )

    scope = load_goal_acceptance_scope(tmp_path)

    assert scope["valid"] is False
    assert scope["validation_errors"] == [
        "unsupported acceptance mode: media_generation=pretend_pass"
    ]
