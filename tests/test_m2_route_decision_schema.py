from pathlib import Path

import yaml

from agent_runtime.routing.route_decision import RouteDecision


def test_route_decision_round_trip(tmp_path: Path) -> None:
    decision = RouteDecision(
        project_id="demo",
        phase_id="phase1",
        task_id="task1",
        role="Coder",
        selected_worker="codex",
        selected_command="codex",
        required_capabilities=["file_edit", "patch_generation"],
        activation_decision="require_approval",
        approval_required=True,
    )
    path = decision.write(tmp_path / "route.yml")
    loaded = RouteDecision.from_dict(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert loaded.selected_worker == "codex"
    assert loaded.approval_required is True
    assert loaded.validate() == []
