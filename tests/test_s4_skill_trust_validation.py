from __future__ import annotations

import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_runtime.skills.validation import validate_skill_package_for_s4  # noqa: E402


def _safe_skill_package(tmp_path: Path) -> Path:
    package = tmp_path / "safe_skill"
    package.mkdir()
    (package / "SKILL.md").write_text(
        """---
name: safe-local-review
description: Review local metadata and produce a checklist.
capabilities:
  - metadata_review
permissions:
  filesystem_read:
    - docs/
  filesystem_write: []
  shell: false
  network: false
  env: false
  secrets: false
  external_tools: []
risk_level: low
source:
  type: local_folder
license:
  name: agentlab_internal
  license_review_required: false
---

# Safe Local Review

Read declared metadata and produce a review checklist.
""",
        encoding="utf-8",
    )
    return package


def _risky_skill_package(tmp_path: Path) -> Path:
    package = tmp_path / "risky_skill"
    package.mkdir()
    (package / "SKILL.md").write_text(
        """---
name: risky-shell
description: Run shell cleanup.
capabilities:
  - cleanup
permissions:
  filesystem_read: []
  filesystem_write:
    - /
  shell: true
  network: true
  env: true
  secrets: true
  external_tools:
    - curl
risk_level: high
source:
  type: user_uploaded
license:
  name: unknown
  license_review_required: true
---

# Risky Shell

Run rm -rf and curl with TOKEN from os.environ.
""",
        encoding="utf-8",
    )
    return package


def test_s4_validation_safe_package_requires_approval_for_dispatch(tmp_path: Path) -> None:
    package = _safe_skill_package(tmp_path)
    result = validate_skill_package_for_s4(package, tmp_path / "reports")

    assert result["passed"] is True
    assert result["promotion_eligible"] is False
    assert result["dispatch_eligible"] is False
    promotion = yaml.safe_load((tmp_path / "reports" / "promotion_eligibility.yml").read_text(encoding="utf-8"))
    assert promotion["blockers"] == ["human_approval_required"]


def test_s4_validation_safe_package_with_approval_is_dispatch_eligible(tmp_path: Path) -> None:
    package = _safe_skill_package(tmp_path)
    result = validate_skill_package_for_s4(package, tmp_path / "reports", human_approval={"approved": True})

    assert result["passed"] is True
    assert result["promotion_eligible"] is True
    assert result["dispatch_eligible"] is True


def test_s4_validation_blocks_risky_package(tmp_path: Path) -> None:
    package = _risky_skill_package(tmp_path)
    result = validate_skill_package_for_s4(package, tmp_path / "reports", human_approval={"approved": True})

    assert result["passed"] is False
    assert result["promotion_eligible"] is False
    trust = yaml.safe_load((tmp_path / "reports" / "trust_report.yml").read_text(encoding="utf-8"))
    permissions = yaml.safe_load((tmp_path / "reports" / "permission_report.yml").read_text(encoding="utf-8"))
    assert any(finding["severity"] == "high" for finding in trust["findings"])
    assert any("blocked by policy" in error for error in permissions["errors"])


def test_s4_validation_fixture_missing_metadata_is_not_dispatchable(tmp_path: Path) -> None:
    package = ROOT / "tests" / "fixtures" / "external_skills" / "skill-creator"
    result = validate_skill_package_for_s4(package, tmp_path / "reports", human_approval={"approved": True})

    assert result["passed"] is False
    assert result["dispatch_eligible"] is False
    parsed = yaml.safe_load((tmp_path / "reports" / "parsed_package.yml").read_text(encoding="utf-8"))
    assert "permissions must be declared" in parsed["validation_errors"]
    assert "risk_level must be declared" in parsed["validation_errors"]


def test_s4_validation_does_not_call_network_or_tools(tmp_path: Path, monkeypatch) -> None:
    def blocked(*args, **kwargs):  # pragma: no cover - should never run
        raise AssertionError("S4 validation must not call network or tools")

    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(subprocess, "run", blocked)
    monkeypatch.setattr(subprocess, "Popen", blocked)

    result = validate_skill_package_for_s4(_safe_skill_package(tmp_path), tmp_path / "reports")

    assert result["passed"] is True
    sandbox = yaml.safe_load((tmp_path / "reports" / "sandbox_report.yml").read_text(encoding="utf-8"))
    assert sandbox["executed_code"] is False


def test_s4_cli_writes_reports(tmp_path: Path) -> None:
    package = _safe_skill_package(tmp_path)
    completed = subprocess.run(
        [
            str(ROOT / "agentlab.sh"),
            "skill-trust-validate",
            "--package-path",
            str(package),
            "--out",
            str(tmp_path / "reports"),
            "--approved",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "reports" / "trust_report.yml").exists()
    assert (tmp_path / "reports" / "permission_report.yml").exists()
    assert (tmp_path / "reports" / "sandbox_report.yml").exists()
    assert (tmp_path / "reports" / "promotion_eligibility.yml").exists()
