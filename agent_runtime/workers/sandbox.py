"""Sandbox execution environment for safe worker auditioning."""

import shutil
import tempfile
from pathlib import Path
from typing import Any, Generator



class AuditionSandbox:
    def __init__(self) -> None:
        self.temp_dir: tempfile.TemporaryDirectory | None = None
        self.path: Path | None = None

    def __enter__(self) -> "AuditionSandbox":
        self.temp_dir = tempfile.TemporaryDirectory(prefix="agentlab_audition_")
        self.path = Path(self.temp_dir.name)
        # Create a mock repository setup inside the sandbox
        self.setup_mock_repo()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self.temp_dir:
            self.temp_dir.cleanup()

    def setup_mock_repo(self) -> None:
        if not self.path:
            return
        # Create a standard mock layout
        repo_dir = self.path / "mock_repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        
        # Create dummy code files
        (repo_dir / "main.py").write_text(
            "def calculate_total(items):\n    return sum(items)\n",
            encoding="utf-8"
        )
        (repo_dir / "utils.py").write_text(
            "def format_currency(val):\n    return f'${val:.2f}'\n",
            encoding="utf-8"
        )
        
        # Create a basic test file
        tests_dir = repo_dir / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        (tests_dir / "test_main.py").write_text(
            "from main import calculate_total\ndef test_calculate():\n    assert calculate_total([1, 2]) == 3\n",
            encoding="utf-8"
        )
        
        # Create basic package files
        (repo_dir / "pyproject.toml").write_text(
            "[project]\nname = 'mock_repo'\nversion = '0.1.0'\n",
            encoding="utf-8"
        )
