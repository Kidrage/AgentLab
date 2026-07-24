from pathlib import Path
from types import SimpleNamespace


def test_revision_support_disables_generic_patch_application(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent_runtime.narrative.audit.runtime import run_revision_support_role

    run_dir = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "task_audit"
    run_dir.mkdir(parents=True)
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        "agent_runtime.workflow_plan.build_workflow_plan",
        lambda *_args, **_kwargs: SimpleNamespace(run_dir=str(run_dir)),
    )

    def fake_run_agent_model(*_args, **kwargs):
        observed["apply_patches"] = kwargs.get("apply_patches")
        return SimpleNamespace(
            provider="fixture",
            model="fixture",
            status="completed",
            content="fixture",
        )

    monkeypatch.setattr(
        "agent_runtime.agent_runner.run_agent_model",
        fake_run_agent_model,
    )
    monkeypatch.setattr(
        "agent_runtime.narrative_heavy_audit.materialize_narrative_heavy_audit_result",
        lambda *_args, **_kwargs: True,
    )

    result = run_revision_support_role(
        tmp_path,
        project="Crown_of_Ash",
        task_id="task_audit",
        role="Scribe",
    )

    assert result["success"] is True
    assert observed["apply_patches"] is False
