import os
import pytest
from pathlib import Path
from agent_runtime.control_panel.worker_control import WorkerControl

def test_worker_control(tmp_path):
    # Setup
    wc = WorkerControl(tmp_path)
    
    # Disable a worker
    wc.disable_worker("codex")
    assert wc.state.is_disabled("workers", "codex") == True
    
    # Enable a worker
    wc.enable_worker("codex")
    assert wc.state.is_disabled("workers", "codex") == False
    
    # Force assign
    wc.force_assign_role("codex", "Coder")
    overrides = wc.get_overrides("codex")
    assert overrides["force_role"] == "Coder"
    
    # Reset
    wc.reset_assignment("codex")
    overrides = wc.get_overrides("codex")
    assert "force_role" not in overrides
