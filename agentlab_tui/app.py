import sys
from .snapshot_renderer import render_tui_snapshot

def run_tui():
    """Start the interactive TUI, or print fallback if unsupported."""
    try:
        import rich
    except ImportError:
        print("Optional dependency 'rich' or 'textual' not found.")
        print("Falling back to snapshot overview...")
        print(render_tui_snapshot(project=None, view="overview"))
        sys.exit(0)
        
    try:
        import textual
    except ImportError:
        print("Optional dependency 'textual' not found. Cannot launch interactive UI.")
        print("Falling back to snapshot overview...")
        print(render_tui_snapshot(project=None, view="overview"))
        sys.exit(0)
        
    print("Launching full interactive TUI (stub for testing)...")
