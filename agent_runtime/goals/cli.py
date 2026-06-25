import typer
from pathlib import Path
from agent_runtime.goals.action_schema import GoalActionSchema
from agent_runtime.goals.parser import parse_goal_command
from agent_runtime.goals.__init__ import execute_goal_action

def _get_root(out: Path):
    from agent_runtime.run_task import _PROJECT_ROOT
    return out if out else _PROJECT_ROOT

def register_goal_commands(app: typer.Typer):
    @app.command("set")
    def goal_set(
        text: str = typer.Option("", "--text", help="Rough requirement text"),
        prompt_file: Path = typer.Option(None, "--prompt-file", help="Path to prompt.md"),
        project: str = typer.Option("AgentLab", "--project"),
        out: Path = typer.Option(None, "--out", help="Output directory"),
    ):
        if prompt_file and prompt_file.exists():
            text = prompt_file.read_text(encoding="utf-8").strip()
            
        action = GoalActionSchema(command="/goal", action="set", source="cli", project=project, text=text, language="en")
        
        result = execute_goal_action(action, _get_root(out))
        print(f"Status: {result.status}")
        print(f"Message: {result.message}")
        print(f"Artifacts: {result.artifacts}")

    @app.command("plan")
    def goal_plan(project: str = typer.Option("AgentLab", "--project"), out: Path = typer.Option(None, "--out")):
        action = GoalActionSchema(command="/goal", action="plan", source="cli", project=project)
        result = execute_goal_action(action, _get_root(out))
        print(f"Status: {result.status}")

    @app.command("status")
    def goal_status(project: str = typer.Option("AgentLab", "--project"), out: Path = typer.Option(None, "--out")):
        action = GoalActionSchema(command="/goal", action="status", source="cli", project=project)
        result = execute_goal_action(action, _get_root(out))
        print(f"Status: {result.status}")

    @app.command("progress")
    def goal_progress(project: str = typer.Option("AgentLab", "--project"), out: Path = typer.Option(None, "--out")):
        action = GoalActionSchema(command="/goal", action="progress", source="cli", project=project)
        result = execute_goal_action(action, _get_root(out))
        print(f"Status: {result.status}")

    @app.command("validate")
    def goal_validate(project: str = typer.Option("AgentLab", "--project"), out: Path = typer.Option(None, "--out")):
        action = GoalActionSchema(command="/goal", action="validate", source="cli", project=project)
        result = execute_goal_action(action, _get_root(out))
        print(f"Status: {result.status}")

    @app.command("report")
    def goal_report(project: str = typer.Option("AgentLab", "--project"), out: Path = typer.Option(None, "--out")):
        action = GoalActionSchema(command="/goal", action="report", source="cli", project=project)
        result = execute_goal_action(action, _get_root(out))
        print(f"Status: {result.status}")
        
    @app.command("pause")
    def goal_pause(project: str = typer.Option("AgentLab", "--project"), out: Path = typer.Option(None, "--out")):
        action = GoalActionSchema(command="/goal", action="pause", source="cli", project=project)
        result = execute_goal_action(action, _get_root(out))
        print(f"Status: {result.status}")
        
    @app.command("resume")
    def goal_resume(project: str = typer.Option("AgentLab", "--project"), out: Path = typer.Option(None, "--out")):
        action = GoalActionSchema(command="/goal", action="resume", source="cli", project=project)
        result = execute_goal_action(action, _get_root(out))
        print(f"Status: {result.status}")
        
    @app.command("close")
    def goal_close(project: str = typer.Option("AgentLab", "--project"), out: Path = typer.Option(None, "--out")):
        action = GoalActionSchema(command="/goal", action="close", source="cli", project=project)
        result = execute_goal_action(action, _get_root(out))
        print(f"Status: {result.status}")

    @app.command("parse")
    def goal_parse(text: str, project: str = typer.Option("AgentLab", "--project")):
        action = parse_goal_command(text, project=project, source="cli")
        import json
        print(json.dumps(action.to_dict(), indent=2))
