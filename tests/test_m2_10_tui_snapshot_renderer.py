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
    assert "Project: Demo (Known: True)" in snap
    assert "Next Safe Action" in snap

def test_headless_snapshot_workers():
    snap = render_tui_snapshot(project="Demo", view="workers")
    assert "Worker Registry:" in snap

def test_headless_snapshot_costs():
    snap = render_tui_snapshot(project="Demo", view="costs")
    assert "Total Cost: $" in snap
