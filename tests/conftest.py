from __future__ import annotations

from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def private_crown_project_root() -> Path:
    """Require the ignored local Crown project for private acceptance tests."""
    project_root = ROOT / "projects" / "Crown_of_Ash"
    if not project_root.is_dir():
        pytest.skip("requires local ignored projects/Crown_of_Ash acceptance evidence")
    return ROOT


@pytest.fixture
def isolated_agentlab_root(tmp_path: Path) -> Path:
    """Return a writable AgentLab root that cannot mutate repository state."""
    root = tmp_path / "agentlab"
    root.mkdir()
    (root / "agentlab.sh").symlink_to(ROOT / "agentlab.sh")
    (root / "agent_runtime").mkdir()
    shutil.copytree(ROOT / "config", root / "config")
    shutil.copytree(ROOT / "agent_templates", root / "agent_templates")
    (root / "skills" / "active").mkdir(parents=True)
    (root / "skills" / "registry.yml").write_text("skills: []\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# Isolated test workspace\n", encoding="utf-8")

    project = root / "projects" / "AgentLab"
    (project / "repo").mkdir(parents=True)
    (project / "agent_docs").mkdir()
    (project / "project_config.yml").write_text(
        "name: AgentLab\npaths:\n  repo: repo\n  docs: agent_docs\n  runs: runs\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def isolated_agentlab_cli_root(isolated_agentlab_root: Path) -> Path:
    """Add a clean runtime copy for subprocess CLI integration tests."""
    shutil.copytree(
        ROOT / "agent_runtime",
        isolated_agentlab_root / "agent_runtime",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(".env", ".venv", "__pycache__", "*.pyc"),
    )
    return isolated_agentlab_root
