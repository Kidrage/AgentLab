import typer
from pathlib import Path
from rich.console import Console
from .modes import handle_ask
from .route_explainer import explain_route
from .worker_explainer import explain_worker
from .state_reader import explain_phase, explain_cost

console = Console()

def register_assistant_commands(app: typer.Typer):
    @app.command("ask")
    def ask_cmd(
        project: str = typer.Option(..., "--project", help="Project ID"),
        question: str = typer.Argument(..., help="Question to ask")
    ):
        """Ask a question about the project state."""
        result = handle_ask(project, question)
        console.print(result)

    @app.command("explain-phase")
    def explain_phase_cmd(
        project: str = typer.Option(..., "--project", help="Project ID"),
        phase: str = typer.Option(..., "--phase", help="Phase ID")
    ):
        """Explain the status and details of a phase."""
        result = explain_phase(project, phase)
        console.print(result)

    @app.command("explain-cost")
    def explain_cost_cmd(
        project: str = typer.Option(..., "--project", help="Project ID")
    ):
        """Explain project cost accumulations."""
        result = explain_cost(project)
        console.print(result)

    @app.command("explain-route")
    def explain_route_cmd(
        decision: Path = typer.Option(..., "--decision", exists=True, dir_okay=False, resolve_path=True)
    ):
        """Explain why a route or worker was chosen."""
        result = explain_route(decision)
        console.print(result)

    @app.command("explain-worker")
    def explain_worker_cmd(
        worker: str = typer.Option(..., "--worker", help="Worker ID")
    ):
        """Explain worker setup and diagnose issues."""
        result = explain_worker(worker)
        console.print(result)

