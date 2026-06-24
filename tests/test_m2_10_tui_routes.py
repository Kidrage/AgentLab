import pytest
from agentlab_tui.snapshot_renderer import render_tui_snapshot

def test_tui_routes_view_rendering():
    """
    Test that the TUI can render route decisions correctly
    in headless snapshot mode.
    """
    # M2-10 specifies we should test route/assignment view
    # renders route decisions.
    snap = render_tui_snapshot(project="Demo", view="routes")
    
    # Verify the view header matches our route view
    assert "View: routes" in snap
    
    # Verify the placeholder route decisions line is printed
    assert "Route Decisions:" in snap

def test_tui_routes_unknown_view():
    """
    Test that passing an invalid view to the headless renderer
    gracefully complains instead of crashing.
    """
    snap = render_tui_snapshot(project="Demo", view="invalid_view_name")
    assert "Unknown view: invalid_view_name" in snap
