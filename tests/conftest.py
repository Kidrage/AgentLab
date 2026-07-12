from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def private_crown_project_root() -> Path:
    """Require the ignored local Crown project for private acceptance tests."""
    project_root = ROOT / "projects" / "Crown_of_Ash"
    if not project_root.is_dir():
        pytest.skip("requires local ignored projects/Crown_of_Ash acceptance evidence")
    return ROOT
