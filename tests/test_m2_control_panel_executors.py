import os
import pytest
from pathlib import Path
from agent_runtime.control_panel.executor_control import ExecutorControl

def test_executor_control(tmp_path):
    ec = ExecutorControl(tmp_path)
    ec.disable_executor("local_shell")
    assert ec.state.is_disabled("executors", "local_shell") == True
    
    ec.enable_executor("local_shell")
    assert ec.state.is_disabled("executors", "local_shell") == False
