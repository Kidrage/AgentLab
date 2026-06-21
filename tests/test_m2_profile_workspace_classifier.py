"""Tests for profile_workspace_classifier."""

from pathlib import Path
from agent_runtime.runtime_hygiene.profile_workspace_classifier import (
    classify_entry,
    ProfileClass,
    WorkspaceClass,
)

def test_classify_profiles():
    # Profile cases
    cat, cls = classify_entry("/foo/bar/.agents/profiles/claude")
    assert cat == "profile"
    assert cls == ProfileClass.CLAUDE

    cat, cls = classify_entry("/foo/bar/.agents/profiles/nonexistent")
    assert cat == "profile"
    assert cls == ProfileClass.UNKNOWN

def test_classify_workspaces():
    # Workspace cases
    cat, cls = classify_entry("/foo/bar/.agents/workspaces/claude")
    assert cat == "workspace"
    assert cls == WorkspaceClass.CLAUDE

    cat, cls = classify_entry("/foo/bar/.agents/workspaces/generic_cli")
    assert cat == "workspace"
    assert cls == WorkspaceClass.GENERIC_CLI

    cat, cls = classify_entry("/foo/bar/.agents/workspaces/nonexistent")
    assert cat == "workspace"
    assert cls == WorkspaceClass.UNKNOWN

def test_classify_unknown():
    cat, cls = classify_entry("/foo/bar/.agents/other/claude")
    assert cat == "unknown"
    assert cls is None
