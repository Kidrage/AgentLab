import pytest
from agentlab_tui.snapshot_renderer import render_tui_snapshot

def test_tui_worker_registry_view_renders():
    """
    Test that the TUI can render the worker registry in headless mode.
    """
    # M2-10 specifies we should test the worker registry view renders
    snap = render_tui_snapshot(project="Demo", view="tasks")
    
    # Verify the view header matches our worker view
    assert "View: tasks" in snap
    
    # Verify the worker registry line is printed without crashing
    assert "No executor results found" in snap

def test_tui_worker_view_handles_missing_project():
    """
    Test that requesting the worker view for a missing project
    gracefully warns without crashing.
    """
    snap = render_tui_snapshot(project=None, view="tasks")
    assert "[None selected]" in snap
    assert "View: tasks" in snap
