"""Runtime hygiene and operator-demo CLI commands."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import typer
import yaml
from rich.console import Console

ProjectRootProvider = Path | Callable[[], Path]


def register_runtime_hygiene_commands(app: typer.Typer, project_root: ProjectRootProvider, console: Console) -> None:
    """Register runtime hygiene and deterministic operator demo commands."""

    def current_project_root() -> Path:
        return project_root() if callable(project_root) else project_root

    @app.command("m2-operator-demo")
    def m2_operator_demo_cmd(
        out: Path = typer.Option(Path("acceptance_runs/m2_operator_demo"), "--out"),
        project: str = typer.Option("AgentLab", "--project"),
        strict_migration: bool = typer.Option(False, "--strict-migration"),
    ) -> None:
        """Run the deterministic M2-12 operator acceptance demo."""
        from agent_runtime.m2_operator_demo import run_m2_operator_demo

        root = current_project_root()
        summary = run_m2_operator_demo(root, out, project=project, strict_migration=strict_migration)
        console.print(f"M2-12 operator demo status: {summary['status']}")
        if strict_migration and summary["migration"].get("demo_blocking_failures"):
            console.print("Strict migration failures:")
            for item in summary["migration"]["demo_blocking_failures"]:
                console.print(f"- {item.get('id')}: {item.get('message')}")
        report_root = Path(out) if Path(out).is_absolute() else root / out
        console.print(f"Report written to {report_root / 'M2_OPERATOR_OS_EXECUTION_ECONOMY_REPORT.md'}")

    @app.command("runtime-doctor")
    def runtime_doctor(
        out: Path = typer.Option(Path("acceptance_runs/m2_runtime_hygiene"), "--out"),
    ) -> None:
        """Run layout scan, symlink audit, gitignore audit, and secret scan. Render Markdown/YAML reports."""
        from agent_runtime.runtime_hygiene.gitignore_audit import audit_gitignore
        from agent_runtime.runtime_hygiene.layout import scan_layout
        from agent_runtime.runtime_hygiene.renderer import render_layout_markdown, render_layout_yaml
        from agent_runtime.runtime_hygiene.secret_scan import scan_secrets
        from agent_runtime.runtime_hygiene.symlink_audit import audit_symlinks

        root = current_project_root()
        layout_report = scan_layout(root)
        symlink_audit = audit_symlinks(root)
        gitignore_audit = audit_gitignore(root)
        secret_scan = scan_secrets(root)

        out.mkdir(parents=True, exist_ok=True)
        md_content = render_layout_markdown(layout_report, symlink_audit, gitignore_audit, secret_scan)
        yaml_content = render_layout_yaml(layout_report, symlink_audit, gitignore_audit, secret_scan)

        (out / "M2_RUNTIME_HYGIENE_REPORT.md").write_text(md_content, encoding="utf-8")
        (out / "M2_RUNTIME_HYGIENE_REPORT.yml").write_text(yaml_content, encoding="utf-8")

        console.print(f"Hygiene audit finished. Reports written to {out}")
        console.print(md_content)

    @app.command("runtime-layout")
    def runtime_layout() -> None:
        """Scan and print the runtime layout."""
        from agent_runtime.runtime_hygiene.layout import scan_layout

        layout_report = scan_layout(current_project_root())
        console.print(yaml.safe_dump(layout_report.to_dict(), sort_keys=False, allow_unicode=True))

    @app.command("runtime-audit-symlinks")
    def runtime_audit_symlinks() -> None:
        """Audit all symlinks and print the results."""
        from agent_runtime.runtime_hygiene.symlink_audit import audit_symlinks

        symlink_audit = audit_symlinks(current_project_root())
        console.print(yaml.safe_dump(symlink_audit.to_dict(), sort_keys=False, allow_unicode=True))

    @app.command("runtime-secret-scan")
    def runtime_secret_scan() -> None:
        """Scan for secrets and print findings."""
        from agent_runtime.runtime_hygiene.secret_scan import scan_secrets

        secret_scan = scan_secrets(current_project_root())
        console.print(yaml.safe_dump(secret_scan.to_dict(), sort_keys=False, allow_unicode=True))
