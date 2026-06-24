import pytest
from agentlab_tui.screens import WorkerRegistryScreen, RoleAssignmentScreen

def test_worker_registry_view_works():
    assert WorkerRegistryScreen.name == "Worker Registry"

def test_role_assignment_view_works():
    assert RoleAssignmentScreen.name == "Role Assignment Matrix"
