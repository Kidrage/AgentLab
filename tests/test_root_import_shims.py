from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_root_atomic_io_shim_exports_full_runtime_read_helpers() -> None:
    spec = importlib.util.spec_from_file_location("root_atomic_io_shim", ROOT / "atomic_io.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for name in [
        "atomic_write_text",
        "atomic_write_yaml",
        "atomic_write_json",
        "safe_read_yaml",
        "safe_read_json",
        "safe_read_text",
    ]:
        assert hasattr(module, name)
        assert name in module.__all__


def test_package_import_does_not_depend_on_agent_runtime_sys_path_injection() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from atomic_io import safe_read_json, safe_read_text; "
            "import agent_runtime.skills.inventory; "
            "print('import_ok')",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "import_ok" in result.stdout
