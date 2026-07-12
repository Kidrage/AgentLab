from __future__ import annotations

from agent_runtime.control_panel.capability_control import CapabilityControl
from agent_runtime.control_panel.executor_control import ExecutorControl
from agent_runtime.control_panel.skill_control import SkillControl
from agent_runtime.control_panel.worker_control import WorkerControl


def test_control_panel_toggles_capabilities_executors_and_skills(tmp_path) -> None:
    cases = (
        (CapabilityControl, "disable_capability", "enable_capability", "capabilities", "vision"),
        (ExecutorControl, "disable_executor", "enable_executor", "executors", "local_shell"),
        (SkillControl, "disable_skill", "enable_skill", "skills", "file_editor"),
    )
    for index, (control_type, disable, enable, namespace, item_id) in enumerate(cases):
        control = control_type(tmp_path / str(index))
        getattr(control, disable)(item_id)
        assert control.state.is_disabled(namespace, item_id) is True
        getattr(control, enable)(item_id)
        assert control.state.is_disabled(namespace, item_id) is False


def test_worker_control_toggles_and_resets_forced_role(tmp_path) -> None:
    control = WorkerControl(tmp_path)

    control.disable_worker("codex")
    assert control.state.is_disabled("workers", "codex") is True
    control.enable_worker("codex")
    assert control.state.is_disabled("workers", "codex") is False

    control.force_assign_role("codex", "Coder")
    assert control.get_overrides("codex")["force_role"] == "Coder"
    control.reset_assignment("codex")
    assert "force_role" not in control.get_overrides("codex")
