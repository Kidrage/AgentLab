from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]

PYTHON_SCAN_ROOTS = [
    ROOT / "agent_runtime",
    ROOT / "tests",
]

YAML_SCAN_ROOTS = [
    ROOT / "config",
    ROOT / ".github" / "workflows",
]

KNOWN_TINY_PYTHON_FILES = {
    "state_store.py",
    "atomic_io.py",
    "agent_runtime/ingestion/__init__.py",
    "agent_runtime/ingestion/repo_indexers/__init__.py",
    "agent_runtime/search/__init__.py",
    "agent_runtime/skills/__init__.py",
    "agent_runtime/external_agents/__init__.py",
    "agent_runtime/costing/__init__.py",
}

MIN_LINE_COUNTS = {
    ".github/workflows/ci.yml": 15,
    "agent_runtime/mcp_server.py": 100,
    "agent_runtime/skills/registry.py": 80,
    "agent_runtime/external_agents/ecc_inventory.py": 80,
    "agent_runtime/external_agents/handoff.py": 80,
    "agent_runtime/search/anysearch_adapter.py": 80,
    "agent_runtime/search/local_url_reader.py": 40,
    "agent_runtime/ingestion/repo_indexers/codegraph_adapter.py": 80,
    "agent_runtime/repo_index_cli.py": 40,
    "tests/test_anysearch_adapter.py": 40,
    "tests/test_p1_cd_syntax_yaml_integrity.py": 40,
    "tests/test_external_skill_registry.py": 40,
    "tests/test_repository_text_integrity.py": 80,
    "config/search_providers.yml": 10,
    "config/repo_indexing.yml": 10,
}


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in PYTHON_SCAN_ROOTS:
        files.extend(
            path
            for path in root.rglob("*.py")
            if "__pycache__" not in path.parts and ".venv" not in path.parts
        )
    for path in [ROOT / "agentlab_app.py", ROOT / "state_store.py", ROOT / "atomic_io.py"]:
        if path.exists():
            files.append(path)
    return sorted(set(files))


def _yaml_files() -> list[Path]:
    files: list[Path] = []
    for root in YAML_SCAN_ROOTS:
        files.extend(path for path in root.rglob("*.yml"))
        files.extend(path for path in root.rglob("*.yaml"))
    return sorted(set(files))


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _max_line_length(path: Path) -> int:
    lines = path.read_text(encoding="utf-8").splitlines()
    return max((len(line) for line in lines), default=0)


def test_repository_python_files_parse() -> None:
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))


def test_repository_yaml_files_parse() -> None:
    for path in _yaml_files():
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data is None or isinstance(data, (dict, list)), _relative(path)


def test_github_workflows_have_required_top_level_keys() -> None:
    workflow_dir = ROOT / ".github" / "workflows"
    workflows = sorted(workflow_dir.glob("*.yml")) + sorted(workflow_dir.glob("*.yaml"))
    assert workflows, "No GitHub Actions workflows found"

    for path in workflows:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), _relative(path)
        for key in ("name", "on", "jobs"):
            assert key in data, f"{_relative(path)} missing top-level {key!r}"


def test_known_p1_files_have_reasonable_line_counts() -> None:
    for relative_path, minimum in MIN_LINE_COUNTS.items():
        path = ROOT / relative_path
        assert path.exists(), f"{relative_path} missing"
        count = _line_count(path)
        assert count >= minimum, f"{relative_path} has only {count} lines"


def test_python_files_do_not_look_single_line_compressed() -> None:
    for path in _python_files():
        relative_path = _relative(path)
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()

        if relative_path not in KNOWN_TINY_PYTHON_FILES and path.name != "__init__.py":
            assert len(lines) >= 10, f"{relative_path} has only {len(lines)} lines"

        assert _max_line_length(path) <= 1200, (
            f"{relative_path} has a line over 1200 characters"
        )

        for number, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            if stripped.startswith('"""') and "from __future__ import annotations" in line:
                raise AssertionError(
                    f"{relative_path}:{number} has docstring and future import on one line"
                )

            top_level_defs = len(re.findall(r"(?<!\w)(?:class|def)\s+\w+", line))
            assert top_level_defs <= 1, (
                f"{relative_path}:{number} has multiple class/def statements on one line"
            )
