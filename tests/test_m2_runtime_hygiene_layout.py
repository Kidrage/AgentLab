"""Tests for runtime layout scanning in agent_runtime.runtime_hygiene.layout."""

import os
from pathlib import Path
from agent_runtime.runtime_hygiene.layout import scan_layout, LayoutReport

def test_scan_layout_creates_directories(tmp_path):
    # Running scan_layout on an empty directory should create the required layout structure.
    layout_report = scan_layout(tmp_path)
    
    assert isinstance(layout_report, LayoutReport)
    data = layout_report.to_dict()
    
    assert data["agentlab_root"] == str(tmp_path)
    
    # Check that directories were created
    assert (tmp_path / ".agents" / "profiles").is_dir()
    assert (tmp_path / ".agents" / "workspaces").is_dir()
    assert (tmp_path / ".agents" / "bridges").is_dir()
    assert (tmp_path / ".agents" / "logs").is_dir()
    assert (tmp_path / ".agents" / "runtime").is_dir()

def test_scan_layout_detects_entries(tmp_path):
    # Pre-create some layout structures
    profiles_dir = tmp_path / ".agents" / "profiles"
    workspaces_dir = tmp_path / ".agents" / "workspaces"
    
    profiles_dir.mkdir(parents=True)
    workspaces_dir.mkdir(parents=True)
    
    # Create an actual profile dir
    (profiles_dir / "claude").mkdir()
    
    # Create a workspace dir
    (workspaces_dir / "qwen").mkdir()
    
    # Create a broken symlink profile
    broken_sym = profiles_dir / "hermes"
    broken_sym.symlink_to("nonexistent_target_path")
    
    layout_report = scan_layout(tmp_path)
    data = layout_report.to_dict()
    
    # Check profiles
    profile_entries = {entry["name"]: entry for entry in data["profile_entries"]}
    assert profile_entries["claude"]["exists"] is True
    assert profile_entries["claude"]["symlink"] is False
    
    assert profile_entries["hermes"]["exists"] is False
    assert profile_entries["hermes"]["symlink"] is True
    assert profile_entries["hermes"]["target"] == "nonexistent_target_path"
    assert "broken_symlink" in profile_entries["hermes"]["risk_flags"]
    
    # Check workspaces
    workspace_entries = {entry["name"]: entry for entry in data["workspace_entries"]}
    assert workspace_entries["qwen"]["exists"] is True
    assert workspace_entries["qwen"]["symlink"] is False
    assert workspace_entries["qwen"]["cleanable"] is True
