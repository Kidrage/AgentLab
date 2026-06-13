import subprocess
import sys


def test_executor_router_cli_dry_run(tmp_path):
    out = tmp_path / "dry"
    result = subprocess.run([sys.executable, "scripts/p2_executor_router_check.py", "--task-type", "repo_patch", "--summary", "Patch", "--output", str(out), "--mode", "dry-run"], text=True, capture_output=True)
    assert result.returncode == 0
    assert (out / "route_report.yml").is_file()


def test_executor_router_cli_mock_mode_passes_review(tmp_path):
    out = tmp_path / "mock"
    result = subprocess.run([sys.executable, "scripts/p2_executor_router_check.py", "--task-type", "repo_patch", "--summary", "Patch", "--output", str(out), "--mode", "mock"], text=True, capture_output=True)
    assert result.returncode == 0
    assert (out / "review" / "review_verdict.yml").is_file()


def test_executor_router_cli_manual_handoff_generates_handoff(tmp_path):
    out = tmp_path / "handoff"
    result = subprocess.run([sys.executable, "scripts/p2_executor_router_check.py", "--task-type", "repo_patch", "--summary", "Patch", "--output", str(out), "--mode", "manual-handoff"], text=True, capture_output=True)
    assert result.returncode == 0
    assert (out / "external_execution_handoff.md").is_file()


def test_executor_router_cli_no_provider_exits_nonzero(tmp_path):
    out = tmp_path / "none"
    result = subprocess.run([sys.executable, "scripts/p2_executor_router_check.py", "--task-type", "video_render", "--summary", "Render", "--output", str(out), "--mode", "dry-run"], text=True, capture_output=True)
    assert result.returncode == 1
