from pathlib import Path
import os
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def _isolated_entrypoint(tmp_path: Path) -> Path:
    root = tmp_path / "AgentLab"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "agentlab.sh", root / "agentlab.sh")
    shutil.copy2(ROOT / "scripts" / "bootstrap.sh", root / "scripts" / "bootstrap.sh")
    return root


def test_bootstrap_help_does_not_require_runtime_dependencies(tmp_path: Path) -> None:
    root = _isolated_entrypoint(tmp_path)
    result = subprocess.run(
        ["bash", str(root / "agentlab.sh"), "bootstrap", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert "Create the project-local virtual environment" in result.stdout


def test_missing_dependencies_report_bootstrap_action_without_traceback(
    tmp_path: Path,
) -> None:
    root = _isolated_entrypoint(tmp_path)
    fake_python = tmp_path / "python-without-agentlab-dependencies"
    fake_python.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    fake_python.chmod(0o755)
    env = os.environ.copy()
    env["PYTHON"] = str(fake_python)

    result = subprocess.run(
        ["bash", str(root / "agentlab.sh"), "repository-handoff", "--repo", "."],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 2
    assert "runtime dependencies are not installed" in result.stderr
    assert "./agentlab.sh bootstrap" in result.stderr
    assert "Traceback" not in result.stderr


def test_lock_contains_every_direct_requirement() -> None:
    direct = {
        line.strip().lower().split("<", 1)[0]
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    locked_text = (ROOT / "requirements.lock").read_text(encoding="utf-8").lower()

    assert direct
    for package in direct:
        assert f"{package}==" in locked_text
