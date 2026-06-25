from agent_runtime.goals.action_schema import GoalActionSchema

def test_assistant_returns_schema():
    from agent_runtime.goals.parser import parse_goal_command
    action = parse_goal_command("/目标 修复", source="assistant")
    assert isinstance(action, GoalActionSchema)
    assert action.source == "assistant"

def test_tui_returns_schema():
    from agent_runtime.goals.parser import parse_goal_command
    action = parse_goal_command("/进度", source="tui")
    assert isinstance(action, GoalActionSchema)
    assert action.source == "tui"

def test_webui_returns_schema():
    from agent_runtime.goals.parser import parse_goal_command
    action = parse_goal_command("/goal set", source="webui")
    assert isinstance(action, GoalActionSchema)
    assert action.source == "webui"

def test_mcp_returns_schema():
    action = GoalActionSchema(command="/goal", text="build novel", source="openclaw", project="NovelProject")
    assert action.source == "openclaw"
    assert action.project == "NovelProject"
