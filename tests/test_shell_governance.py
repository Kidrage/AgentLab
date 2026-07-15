from agent_runtime.shell_governance import shell_execution_plan, validate_production_argv


def test_production_shell_safety_rejects_all_bypass_forms():
    assert validate_production_argv(["hermes", "-z", "task"])
    assert validate_production_argv(["hermes", "--ignore-rules", "task"])
    assert validate_production_argv(
        ["claude", "--permission-mode", "bypassPermissions", "-p", "task"]
    )
    assert validate_production_argv(
        ["claude", "--permission-mode=bypassPermissions", "-p", "task"]
    )
    assert validate_production_argv(
        ["claude", "--allow-dangerously-skip-permissions", "-p", "task"]
    )
    assert validate_production_argv(
        ["claude", "--allow-dangerously-skip-permissions=true", "-p", "task"]
    )
    assert validate_production_argv(["qwen", "--approval-mode", "yolo", "task"])
    assert validate_production_argv(["qwen", "--approval-mode=yolo", "task"])
    assert validate_production_argv(["claude", "--permission-mode", "plan", "-p", "task"]) == []


def test_hermes_native_surfaces_have_distinct_coordination_semantics():
    one = shell_execution_plan("hermes", profile_ref="writer")
    board = shell_execution_plan("hermes", heterogeneous_roles=True)
    delegated = shell_execution_plan("hermes", same_role_parallelism=True)

    assert (one.channel, one.native_surface) == ("api_runs", "run")
    assert board.native_surface == "kanban"
    assert board.coordination_semantics == "durable_cross_role_work"
    assert delegated.native_surface == "delegate_task"
    assert delegated.coordination_semantics == "same_role_short_parallelism"
