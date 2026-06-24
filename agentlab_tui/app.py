from rich.console import Console

console = Console()

class AgentLabTUI:
    def __init__(self):
        self.running = False
        
    def run(self):
        self.running = True
        console.print("[bold green]AgentLab TUI started.[/bold green]")
        # In a real implementation, this would start the event loop.
        
    def show_project_list(self):
        console.print("Loading Project List...")
        
    def show_worker_registry(self):
        console.print("Loading Worker Registry...")
