"""Worker registry, invocation, and audition CLI commands."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.table import Table

ProjectRootProvider = Path | Callable[[], Path]


def register_worker_commands(app: typer.Typer, project_root: ProjectRootProvider, console: Console) -> None:
    """Register worker management and inspection commands."""

    def current_project_root() -> Path:
        return project_root() if callable(project_root) else project_root

    def worker_cache_dir() -> Path:
        return current_project_root() / ".agentlab" / "cache"

    @app.command("worker-scan")
    def worker_scan() -> None:
        """Scan and cache local worker availability."""
        from agent_runtime.workers.registry import WorkerRegistry

        root = current_project_root()
        registry = WorkerRegistry(worker_cache_dir())
        registry.scan_and_register()
        console.print(f"Scanned system and cached workers at {registry.cache_path}")
        from agent_runtime.observability.api import emit_event

        for w in registry.list_workers():
            status = "installed" if w.installed else "missing"
            emit_event(
                "AgentLab",
                root,
                "worker_detected",
                details={"status": status, "version": w.version},
                worker_id=w.worker_id,
            )
            console.print(f"- {w.display_name} ({w.worker_id}): {status} (version: {w.version or 'N/A'})")

    @app.command("worker-list")
    def worker_list() -> None:
        """List all registered workers from cache."""
        from agent_runtime.workers.registry import WorkerRegistry

        registry = WorkerRegistry(worker_cache_dir())
        if not registry.load_from_cache():
            registry.scan_and_register()

        workers_dict = {w.worker_id: w.to_dict() for w in registry.list_workers()}
        print(yaml.safe_dump(workers_dict, sort_keys=False, allow_unicode=True))

    @app.command("worker-inspect")
    def worker_inspect(worker: str = typer.Option(..., "--worker")) -> None:
        """Inspect a specific worker's details."""
        from agent_runtime.workers.registry import WorkerRegistry

        registry = WorkerRegistry(worker_cache_dir())
        if not registry.load_from_cache():
            registry.scan_and_register()

        w = registry.get_worker(worker)
        if not w:
            console.print(f"[red]Error: worker '{worker}' not found.[/red]")
            raise typer.Exit(code=1)

        print(yaml.safe_dump(w.to_dict(), sort_keys=False, allow_unicode=True))

    @app.command("worker-doctor")
    def worker_doctor(
        out: Path = typer.Option(Path("acceptance_runs/m2_worker_registry"), "--out"),
    ) -> None:
        """Scan local workers and generate a markdown doctor report."""
        from agent_runtime.workers.detector import scan_workers
        from agent_runtime.workers.renderer import render_worker_scan_report

        workers = scan_workers()
        out.mkdir(parents=True, exist_ok=True)
        report_content = render_worker_scan_report(workers)

        (out / "worker_scan_report.md").write_text(report_content, encoding="utf-8")
        console.print(f"Worker doctor report written to {out}/worker_scan_report.md\n")
        console.print(report_content)

    @app.command("worker-contracts")
    def worker_contracts() -> None:
        """List all loaded worker invocation contracts."""
        from agent_runtime.workers.invocation_contract import load_contracts

        config_path = current_project_root() / "config" / "worker_invocation_contracts.yml"
        contracts = load_contracts(config_path)
        contracts_dict = {w_id: c.to_dict() for w_id, c in contracts.items()}
        print(yaml.safe_dump(contracts_dict, sort_keys=False, allow_unicode=True))

    @app.command("worker-contract-validate")
    def worker_contract_validate(
        worker: str | None = typer.Option(None, "--worker"),
        all_workers: bool = typer.Option(False, "--all"),
    ) -> None:
        """Validate invocation command templates for workers."""
        from agent_runtime.workers.command_template_validator import validate_template
        from agent_runtime.workers.invocation_contract import load_contracts

        config_path = current_project_root() / "config" / "worker_invocation_contracts.yml"
        contracts = load_contracts(config_path)

        if not worker and not all_workers:
            console.print("[red]Error: Must specify --worker or --all[/red]")
            raise typer.Exit(code=1)

        targets = contracts.keys() if all_workers else [worker]

        has_errors = False
        for t in targets:
            c = contracts.get(t)
            if not c:
                console.print(f"[red]Error: contract for '{t}' not found[/red]")
                has_errors = True
                continue

            valid, errors = validate_template(
                c.template,
                c.required_placeholders,
                allow_unquoted_placeholders=c.validation.allow_unquoted_placeholders,
            )
            if valid:
                console.print(f"[green]✓[/green] {c.display_name} ({t}): Template is valid.")
            else:
                console.print(f"[red]✗[/red] {c.display_name} ({t}): Template has validation errors:")
                for err in errors:
                    console.print(f"  - {err}")
                has_errors = True

        if has_errors:
            raise typer.Exit(code=1)

    @app.command("worker-invocation-probe")
    def worker_invocation_probe(
        worker: str = typer.Option(..., "--worker"),
        mock: bool = typer.Option(False, "--mock"),
    ) -> None:
        """Run a safe probe to test a worker binary."""
        from agent_runtime.workers.cli_error_classifier import classify_cli_error
        from agent_runtime.workers.invocation_contract import load_contracts
        from agent_runtime.workers.safe_probe_runner import run_safe_probe

        root = current_project_root()
        config_path = root / "config" / "worker_invocation_contracts.yml"
        contracts = load_contracts(config_path)

        c = contracts.get(worker)
        if not c:
            console.print(f"[red]Error: contract for '{worker}' not found[/red]")
            raise typer.Exit(code=1)

        exit_code, stdout, stderr, timeout, bin_missing = run_safe_probe(c, mock=mock)

        result = {
            "worker_id": worker,
            "installed": not bin_missing,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "timeout": timeout,
        }

        if bin_missing:
            result["error_class"] = "binary_missing"
        elif exit_code != 0 or timeout:
            result["error_class"] = classify_cli_error(
                exit_code,
                stdout,
                stderr,
                timeout_occurred=timeout,
                config_path=root / "config" / "cli_error_classification.yml",
            )
        else:
            result["error_class"] = "none"

        print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True))

    @app.command("worker-invocation-report")
    def worker_invocation_report(
        out: Path = typer.Option(Path("acceptance_runs/m2_worker_invocation_contracts"), "--out"),
        mock: bool = typer.Option(False, "--mock"),
    ) -> None:
        """Generate a unified report of all invocation contracts, probes, and classifications."""
        from agent_runtime.workers.invocation_report import generate_invocation_report

        generate_invocation_report(current_project_root(), out, mock=mock)
        console.print(f"unified contract validation reports written to {out}")

    @app.command("worker-audition")
    def worker_audition(
        all_workers: bool = typer.Option(False, "--all", help="Audition all workers"),
        worker: str | None = typer.Option(None, "--worker", help="The name of the worker to audition"),
        role: str | None = typer.Option(None, "--role", help="The name of the role to audition (e.g. Coder)"),
        level: str = typer.Option("quick", "--level", help="Audition level (quick, standard, deep)"),
        real: bool = typer.Option(False, "--real", help="Execute real binaries instead of mock simulation"),
    ) -> None:
        """Evaluate local workers via mock simulation or sandboxed execution."""
        from agent_runtime.workers.audition import run_all_auditions, run_single_audition

        root = current_project_root()
        if not all_workers and (not worker or not role):
            console.print("[red]Error: Must specify --all, or both --worker and --role[/red]")
            raise typer.Exit(code=1)

        results = []
        if all_workers:
            console.print(
                f"Starting audition suite (level: [cyan]{level}[/cyan], real: [cyan]{real}[/cyan]) for all workers..."
            )
            results = run_all_auditions(level, real, root)
        else:
            console.print(
                f"Running single audition for worker [cyan]{worker}[/cyan] as [cyan]{role}[/cyan] "
                f"(level: {level}, real: {real})..."
            )
            try:
                res = run_single_audition(worker, role, level, real, root)
                results = [res]
            except Exception as e:
                console.print(f"[red]Audition failed: {str(e)}[/red]")
                raise typer.Exit(code=1)

        from agent_runtime.observability.api import emit_event

        for r in results:
            emit_event(
                project_id="AgentLab",
                project_dir=root,
                event_type="worker_auditioned",
                details={"level": level, "real": real, "passed": getattr(r, "passed", False)},
                worker_id=getattr(r, "worker_id", worker),
                role_id=getattr(r, "role", role),
            )

        table = Table(title="Worker Audition Results")
        table.add_column("Worker ID", style="cyan", no_wrap=True)
        table.add_column("Role")
        table.add_column("Level")
        table.add_column("Verdict", style="bold")
        table.add_column("Role Fit Score", justify="right")
        table.add_column("Cost Score", justify="right")
        table.add_column("Safety Score", justify="right")

        for r in results:
            v_style = "green" if r["verdict"] == "pass" else "red"
            scores = r["scores"]
            table.add_row(
                r["worker_id"],
                r["role"],
                r["level"],
                f"[{v_style}]{r['verdict'].upper()}[/{v_style}]",
                f"{scores['role_fit_score']:.2f}",
                f"{scores['cost_score']:.2f}",
                f"{scores['safety_score']:.2f}",
            )
        console.print(table)

    @app.command("worker-scorecard")
    def worker_scorecard() -> None:
        """Show the consolidated performance scorecards and history for all workers."""
        from agent_runtime.workers.audition import get_scorecard_report_data

        data = get_scorecard_report_data(current_project_root())
        if not data:
            console.print("[yellow]No worker performance ledger found. Please run worker auditions first.[/yellow]")
            return

        table = Table(title="AgentLab Worker Scorecard Ledger")
        table.add_column("Worker ID", style="cyan", no_wrap=True)
        table.add_column("Role Scores")
        table.add_column("Cost Score", justify="right")
        table.add_column("Safety Score", justify="right")
        table.add_column("Last Audition")
        table.add_column("Historical Runs", justify="right")

        for w_id, perf in sorted(data.items()):
            role_scores_str = ", ".join(f"{r}: {s:.2f}" for r, s in perf.get("role_scores", {}).items())
            last = perf.get("last_audition", {})
            last_str = f"{last.get('verdict', '').upper()} ({last.get('suite', '')})" if last else "N/A"
            hist = perf.get("historical_runs", {})
            hist_str = f"{hist.get('success', 0)}/{hist.get('total', 0)}"

            table.add_row(
                w_id,
                role_scores_str or "None",
                f"{perf.get('cost_score', 0.5):.2f}",
                f"{perf.get('safety_score', 0.5):.2f}",
                last_str,
                hist_str,
            )
        console.print(table)
