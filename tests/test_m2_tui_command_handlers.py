import pytest
from agentlab_tui import commands

def test_tui_commands():
    assert commands.handle_approve() == "approved"
    assert commands.handle_reject() == "rejected"
    assert commands.handle_pause() == "paused"
    assert commands.handle_enable_worker("claude_code") == "enabled claude_code"
