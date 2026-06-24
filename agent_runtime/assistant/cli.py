import typer
from pathlib import Path
from rich.console import Console
from .grounding import answer_question
from .models import AssistantQuestion
from .route_explainer import explain_route
from .worker_explainer import explain_worker
from .state_reader import read_project_state

console = Console()

def register_assistant_commands(assistant_app: typer.Typer):
    @assistant_app.command("ask")
    def ask_cmd(
        project: str = typer.Option(..., "--project", help="Project ID"),
        mode: str = typer.Option("operator", "--mode", help="Assistant mode"),
        question: str = typer.Argument(..., help="Question to ask")
    ):
        """Ask a question about the project state."""
        q = AssistantQuestion(mode=mode, project=project, question=question)
        try:
            result = answer_question(q)
            console.print(f"[{result.mode}] Answer: {result.answer}")
            if result.grounding_sources:
                console.print(f"Sources: {[s.path for s in result.grounding_sources]}")
            if result.warnings:
                console.print(f"Warnings: {result.warnings}")
        except Exception as e:
            console.print(f"Error: {e}")

    @assistant_app.command("explain-phase")
    def explain_phase_cmd(
        project: str = typer.Option(..., "--project", help="Project ID"),
        phase: str = typer.Option(..., "--phase", help="Phase ID")
    ):
        """Explain the status and details of a phase."""
        snapshot = read_project_state(project)
        console.print(f"Phase {phase} status: {snapshot.phase_statuses.get(phase, 'unknown')}")

    @assistant_app.command("explain-cost")
    def explain_cost_cmd(
        project: str = typer.Option(..., "--project", help="Project ID")
    ):
        """Explain project cost accumulations."""
        snapshot = read_project_state(project)
        console.print(f"Cost: ${snapshot.cost_summary}")

    @assistant_app.command("explain-route")
    def explain_route_cmd(
        decision: Path = typer.Option(..., "--decision", exists=True, dir_okay=False, resolve_path=True)
    ):
        """Explain why a route or worker was chosen."""
        result = explain_route(decision)
        console.print(result)

    @assistant_app.command("explain-worker")
    def explain_worker_cmd(
        worker: str = typer.Option(..., "--worker", help="Worker ID")
    ):
        """Explain worker setup and diagnose issues."""
        result = explain_worker(worker)
        console.print(result)
