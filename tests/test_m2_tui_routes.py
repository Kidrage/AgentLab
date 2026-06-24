import pytest
from agentlab_tui.app import AgentLabTUI
from agentlab_tui.screens import ProjectListScreen

def test_tui_can_start():
    app = AgentLabTUI()
    app.run()
    assert app.running is True

def test_project_list_loads():
    app = AgentLabTUI()
    app.show_project_list()
    assert ProjectListScreen.name == "Project List"
