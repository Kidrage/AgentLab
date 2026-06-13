from pathlib import Path

import yaml

from agent_runtime.governance.models import GovernanceDecision
from agent_runtime.governance.routing_feedback import generate_routing_recommendations


def _router(tmp_path: Path) -> Path:
    path = tmp_path / "executor_router.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "executor_router": {
                    "providers": [
                        {"provider_id": "healthy", "provider_type": "mock_executor"},
                        {"provider_id": "blocked", "provider_type": "mock_executor"},
                    ],
                    "provider_priority": {"repo_patch": ["healthy", "blocked"]},
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_routing_recommendations_do_not_modify_router_policy(tmp_path: Path):
    router = _router(tmp_path)
    before = router.read_text(encoding="utf-8")
    generate_routing_recommendations([GovernanceDecision("healthy", "HEALTHY")], router, tmp_path)
    assert router.read_text(encoding="utf-8") == before


def test_quarantine_recommendation_apply_automatically_false(tmp_path: Path):
    recs, _warnings = generate_routing_recommendations([GovernanceDecision("blocked", "QUARANTINE_RECOMMENDED")], _router(tmp_path), tmp_path)
    assert recs[0].recommendation == "quarantine"
    assert recs[0].apply_automatically is False


def test_healthy_provider_keep_or_prefer(tmp_path: Path):
    recs, _warnings = generate_routing_recommendations([GovernanceDecision("healthy", "HEALTHY")], _router(tmp_path), tmp_path)
    assert recs[0].recommendation in {"keep", "prefer"}


def test_unknown_provider_warning(tmp_path: Path):
    _recs, warnings = generate_routing_recommendations([GovernanceDecision("missing", "HEALTHY")], _router(tmp_path), tmp_path)
    assert warnings == ["provider not found in router policy: missing"]
