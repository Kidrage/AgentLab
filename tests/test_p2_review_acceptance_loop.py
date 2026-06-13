from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "p2_review_check.py"


def _run_review(target: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--target", str(target), "--output", str(output)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_p2_review_script_passes_good_delivery(tmp_path: Path) -> None:
    proc = _run_review(ROOT / "tests" / "fixtures" / "p2_review" / "good_delivery", tmp_path / "good")
    assert proc.returncode == 0, proc.stderr
    data = yaml.safe_load((tmp_path / "good" / "review_report.yml").read_text(encoding="utf-8"))
    assert data["verdict"]["status"] == "PASS"
    assert not (tmp_path / "good" / "retry_handoff.md").exists()


def test_p2_review_script_fails_unsafe_delivery(tmp_path: Path) -> None:
    proc = _run_review(ROOT / "tests" / "fixtures" / "p2_review" / "unsafe_delivery", tmp_path / "unsafe")
    assert proc.returncode == 1
    data = yaml.safe_load((tmp_path / "unsafe" / "review_report.yml").read_text(encoding="utf-8"))
    assert data["verdict"]["status"] in {"BLOCKED", "FAIL"}
    assert (tmp_path / "unsafe" / "retry_handoff.md").exists()


def test_p2_review_of_p1_acceptance_run_passes(tmp_path: Path) -> None:
    target = ROOT / "acceptance_runs" / "p1_closure"
    proc = _run_review(target, tmp_path / "p1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = yaml.safe_load((tmp_path / "p1" / "review_report.yml").read_text(encoding="utf-8"))
    assert data["verdict"]["status"] == "PASS"
    assert not (tmp_path / "p1" / "retry_handoff.md").exists()
