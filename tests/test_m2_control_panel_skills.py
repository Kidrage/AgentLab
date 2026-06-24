import os
import pytest
from pathlib import Path
from agent_runtime.control_panel.skill_control import SkillControl

def test_skill_control(tmp_path):
    sc = SkillControl(tmp_path)
    sc.disable_skill("file_editor")
    assert sc.state.is_disabled("skills", "file_editor") == True
    
    sc.enable_skill("file_editor")
    assert sc.state.is_disabled("skills", "file_editor") == False
