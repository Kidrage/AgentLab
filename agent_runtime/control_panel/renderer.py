from rich.table import Table

def render_worker_table(workers: list) -> Table:
    table = Table(title="Worker Control Panel")
    table.add_column("Worker ID", style="cyan")
    table.add_column("Installed")
    table.add_column("Version")
    table.add_column("Status", style="bold")
    table.add_column("Force Role")
    for w in workers:
        status_color = "green" if w["status"] == "enabled" else "red"
        table.add_row(
            w["worker_id"],
            "yes" if w["installed"] else "no",
            w["version"] or "N/A",
            f"[{status_color}]{w['status']}[/{status_color}]",
            w["force_role"] or "-"
        )
    return table
