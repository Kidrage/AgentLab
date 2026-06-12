"""Regression test: verify import chains work and no stale cross-tree imports exist.

Commit eabd4a7 introduced a breakage where ``agent_runtime/config_loader.py``
did ``from config.policies import assert_path_allowed`` but ``config/`` is not
a Python package (no __init__.py). This test guard against the same mistake.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENT_RUNTIME = ROOT / "agent_runtime"


def test_py_compile_run_task() -> None:
    """``python -m py_compile agent_runtime/run_task.py`` must succeed.

    This is identical to what ``Validate entrypoints`` runs in CI.
    """
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(AGENT_RUNTIME / "run_task.py")],
        capture_output=True, text=True, timeout=15,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, (
        f"py_compile failed:\n{result.stderr[:800]}"
    )


def test_run_task_import_chain() -> None:
    """Import ``agent_runtime.run_task`` as a module without errors."""
    sys_path = sys.path.copy()
    sys.path.insert(0, str(AGENT_RUNTIME))
    try:
        # Use __import__ so we get a clean import without cached side-effects
        # from conftest or earlier tests.
        import importlib
        spec = importlib.util.find_spec("run_task")
        assert spec is not None, "run_task module not found via agent_runtime/"
        mod = importlib.import_module("run_task")
        assert mod.app is not None, "run_task.app not initialised"
    except ModuleNotFoundError as exc:
        pytest.fail(f"Import chain broken (ModuleNotFoundError): {exc}")
    finally:
        sys.path = sys_path


def test_config_loader_import_uses_runtime_policies_not_config_package() -> None:
    """``agent_runtime/config_loader.py`` must NOT import from ``config``.*.

    The directory ``config/`` is NOT a Python package (no ``__init__.py``).
    All code under ``agent_runtime/`` must use ``from policies import ...``
    which resolves to the ``agent_runtime/policies.py`` sibling module.
    """
    source = (AGENT_RUNTIME / "config_loader.py").read_text(encoding="utf-8")
    blocked = [
        "import config",
        "from config",
    ]
    for pattern in blocked:
        assert pattern not in source, (
            f"Banned import pattern found in config_loader.py: '{pattern}'. "
            f"config/ is not a Python package; use 'from policies import ...' instead."
        )


def test_config_is_not_an_importable_python_package() -> None:
    """``config/`` must not contain ``__init__.py``.

    This project intentionally keeps ``config/`` as a YAML-only directory.
    Turning it into a Python package risks shadowing and circular imports.
    If you need Python code shared across the repo, add it inside
    ``agent_runtime/`` and export through the proxy files at repo root.
    """
    init_path = ROOT / "config" / "__init__.py"
    assert not init_path.exists(), (
        f"{init_path} must not exist. config/ is a YAML directory, "
        f"not a Python package."
    )


def test_proxy_files_exist_and_are_static() -> None:
    """Root proxy files must exist and be pure re-exports without logic."""
    proxies = [
        ("atomic_io.py", "agent_runtime.atomic_io"),
        ("state_store.py", "agent_runtime.state_store"),
    ]
    for filename, expected_module in proxies:
        proxy_path = ROOT / filename
        assert proxy_path.exists(), f"Proxy missing: {filename}"

        content = proxy_path.read_text(encoding="utf-8")
        assert expected_module in content, (
            f"{filename} must import from {expected_module}"
        )
        # Must be a pure re-export: no function/class definitions
        assert "def " not in content, (
            f"{filename} must not define functions; it is a re-export proxy."
        )
        assert "class " not in content, (
            f"{filename} must not define classes; it is a re-export proxy."
        )