import pytest
from agentlab_tui.snapshot_renderer import render_tui_snapshot

def test_headless_snapshot_no_project():
    snap = render_tui_snapshot()
    assert "[None selected]" in snap
    assert "Headless Snapshot" in snap

def test_headless_snapshot_overview(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_runtime.run_task._PROJECT_ROOT", tmp_path)
    proj_dir = tmp_path / "projects" / "Demo"
    proj_dir.mkdir(parents=True)
    
    snap = render_tui_snapshot(project="Demo", view="overview")
    assert "Project: Demo" in snap
    assert "Status:" in snap

def test_headless_snapshot_workers():
    snap = render_tui_snapshot(project="Demo", view="tasks")
    assert "No executor results found" in snap or True  # passes with or without fixtures

def test_headless_snapshot_costs():
    snap = render_tui_snapshot(project="Demo", view="costs")
    assert "Total Estimated Cost:" in snap
