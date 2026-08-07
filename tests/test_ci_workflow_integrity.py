"""Regression test: verify .github/workflows/ci.yml is valid and complete.

Guard against the workflow being compressed into a single line, stripped of
critical validation steps, or otherwise broken in a way GitHub Actions cannot
parse.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

CI_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


def _load_ci() -> dict:
    assert CI_PATH.exists(), f"CI workflow missing: {CI_PATH}"
    raw = CI_PATH.read_text(encoding="utf-8")
    assert len(raw.splitlines()) > 10, (
        f"CI workflow has only {len(raw.splitlines())} lines; "
        f"file may be compressed or truncated."
    )
    data = yaml.safe_load(raw)
    assert isinstance(data, dict), "ci.yml must parse to a dict"
    return data


def test_ci_workflow_top_level_keys() -> None:
    """ci.yml must contain name, on, and jobs."""
    wf = _load_ci()
    # PyYAML 6+ maps 'on' to True in YAML 1.1 mode
    on_key = "on" if "on" in wf else True
    assert on_key in wf, "ci.yml missing top-level 'on' key"
    assert "jobs" in wf, "ci.yml missing top-level 'jobs' key"
    assert "name" in wf and wf["name"] == "CI"


def test_ci_workflow_test_job() -> None:
    """The test job must run on ubuntu-latest."""
    wf = _load_ci()
    jobs = wf.get("jobs", {})
    test_job = jobs.get("test", {})
    assert test_job.get("runs-on") == "ubuntu-latest", (
        f"jobs.test.runs-on must be ubuntu-latest, got {test_job.get('runs-on')!r}"
    )


def test_ci_workflow_steps_present() -> None:
    """All required CI steps must be present."""
    wf = _load_ci()
    test_job = wf.get("jobs", {}).get("test", {})
    steps = test_job.get("steps", [])
    step_names = {s.get("name") for s in steps if "name" in s}

    required = {"Install dependencies", "Validate entrypoints", "Run tests"}
    missing = required - step_names
    assert not missing, f"CI workflow missing steps: {missing}"


def test_ci_validate_entrypoints_commands() -> None:
    """All four Validate entrypoints commands must be present in the run block."""
    wf = _load_ci()
    test_job = wf.get("jobs", {}).get("test", {})
    steps = test_job.get("steps", [])

    validate_step = None
    for s in steps:
        if s.get("name") == "Validate entrypoints":
            validate_step = s
            break
    assert validate_step is not None, "Validate entrypoints step not found"
    assert "run" in validate_step, "Validate entrypoints step missing 'run' key"

    run_text = validate_step["run"]

    required_commands = [
        r"bash\s+-n\s+agentlab\.sh",
        r"python\s+-m\s+py_compile\s+agent_runtime/run_task\.py",
        r"\./agentlab\.sh\s+--help",
        r"\./agentlab\.sh\s+run-pipeline\s+--help",
    ]
    for pattern in required_commands:
        assert re.search(pattern, run_text), (
            f"Validate entrypoints missing command matching: {pattern}\n"
            f"Run text: {run_text[:200]}"
        )


def test_ci_install_dependencies_commands() -> None:
    """Install dependencies must use the hash-locked dependency set."""
    wf = _load_ci()
    test_job = wf.get("jobs", {}).get("test", {})
    steps = test_job.get("steps", [])

    install_step = None
    for s in steps:
        if s.get("name") == "Install dependencies":
            install_step = s
            break
    assert install_step is not None, "Install dependencies step not found"
    assert "run" in install_step

    run_text = install_step["run"]
    assert "pip install --upgrade pip" in run_text or "pip install --upgrade pip" in run_text.lower()
    assert "pip install --require-hashes -r requirements.lock" in run_text
    assert "pip install -r requirements.txt" not in run_text


def test_ci_run_tests_command() -> None:
    """Run tests must execute pytest -q."""
    wf = _load_ci()
    test_job = wf.get("jobs", {}).get("test", {})
    steps = test_job.get("steps", [])

    test_step = None
    for s in steps:
        if s.get("name") == "Run tests":
            test_step = s
            break
    assert test_step is not None, "Run tests step not found"
    assert "run" in test_step
    assert "python -m pytest -q" in test_step["run"]


def test_ci_checkout_and_setup_python() -> None:
    """Checkout v4 and setup-python v5 with python 3.11 must be present."""
    wf = _load_ci()
    test_job = wf.get("jobs", {}).get("test", {})
    steps = test_job.get("steps", [])

    uses_values = [s.get("uses", "") for s in steps]
    assert any("actions/checkout@v4" in u for u in uses_values), (
        "actions/checkout@v4 not found in steps"
    )
    assert any("actions/setup-python@v5" in u for u in uses_values), (
        "actions/setup-python@v5 not found in steps"
    )

    setup_step = None
    for s in steps:
        if "actions/setup-python@v5" in s.get("uses", ""):
            setup_step = s
            break
    assert setup_step is not None
    assert setup_step.get("with", {}).get("python-version") == "3.11", (
        f"python-version must be 3.11, got {setup_step.get('with', {}).get('python-version')!r}"
    )


def test_ci_workflow_yaml_is_not_compressed() -> None:
    """ci.yml must be multi-line, not compressed into a single line."""
    raw = CI_PATH.read_text(encoding="utf-8")
    lines = raw.splitlines()
    assert len(lines) > 10, f"Only {len(lines)} lines — workflow may be compressed"
    # Verify that newlines exist between top-level keys
    assert raw.count("\n") >= 20, f"Only {raw.count(chr(10))} newlines — likely compressed"
