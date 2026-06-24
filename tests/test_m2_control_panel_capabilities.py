import os
import pytest
from pathlib import Path
from agent_runtime.control_panel.capability_control import CapabilityControl

def test_capability_control(tmp_path):
    cc = CapabilityControl(tmp_path)
    cc.disable_capability("vision")
    assert cc.state.is_disabled("capabilities", "vision") == True
    
    cc.enable_capability("vision")
    assert cc.state.is_disabled("capabilities", "vision") == False
