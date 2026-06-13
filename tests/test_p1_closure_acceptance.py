from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "p1_acceptance_check.py"


def _load_acceptance_module():
    spec = importlib.util.spec_from_file_location("p1_acceptance_check", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_p1_external_ops_closed_loop_acceptance(tmp_path: Path) -> None:
    module = _load_acceptance_module()
    output_dir = tmp_path / "p1_closure"

    result = module.run_acceptance(output_dir)

    assert result["verdict"] == "PASS"
    assert all(result["checks"].values())

    required_artifacts = [
        "external_skill_inventory.json",
        "skill_registry.yml",
        "external_handoff.md",
        "anysearch_trace.json",
        "repo_index_status.json",
        "skill_usage_ledger.yml",
        "internal_skill_candidates.yml",
        "p1_acceptance_report.md",
    ]
    for artifact in required_artifacts:
        assert (output_dir / artifact).exists(), artifact

    inventory = yaml.safe_load((output_dir / "external_skill_inventory.json").read_text(encoding="utf-8"))
    assert inventory["scan_mode"] == "static_inventory_only"
    assert inventory["found"] is True
    assert inventory["commands"][0]["executed"] is False
    assert inventory["mcp_servers"][0]["started"] is False

    registry = yaml.safe_load((output_dir / "skill_registry.yml").read_text(encoding="utf-8"))
    imported_external_skills = registry["external_skills"]
    assert imported_external_skills
    assert all(skill["enabled"] is False for skill in imported_external_skills)
    assert all(skill["risk"]["requires_approval"] is True for skill in imported_external_skills)
    assert all(skill["license"]["license_review_required"] is True for skill in imported_external_skills)

    handoff_md = (output_dir / "external_handoff.md").read_text(encoding="utf-8")
    assert "Task Summary" in handoff_md
    assert "Repository Context" in handoff_md
    assert "Acceptance Criteria" in handoff_md
    assert "Evidence Requirements" in handoff_md
    assert "Do not expose secrets" in handoff_md
    assert "Do not execute external tools automatically" in handoff_md
    assert "sk_test_" not in handoff_md
    assert "GITHUB_TOKEN" not in handoff_md

    anysearch_trace = yaml.safe_load((output_dir / "anysearch_trace.json").read_text(encoding="utf-8"))
    assert anysearch_trace["disabled"]["status"] == "skipped"
    assert anysearch_trace["mock"]["status"] == "ok"
    assert anysearch_trace["batch"]["status"] == "pending_approval"
    assert all(item["status"] == "rejected" for item in anysearch_trace["blocked_urls"])

    repo_status = yaml.safe_load((output_dir / "repo_index_status.json").read_text(encoding="utf-8"))
    assert repo_status["disabled_status"]["status"] == "disabled"
    assert repo_status["dry_run"]["performed"] is False
    assert repo_status["remote_decision"]["action"] == "deny"
    assert repo_status["repo_profile_decision"]["action"] == "deny"

    ledger = yaml.safe_load((output_dir / "skill_usage_ledger.yml").read_text(encoding="utf-8"))
    events = {entry["event"] for entry in ledger["entries"]}
    assert {"planned", "skipped", "rejected", "used", "distilled"}.issubset(events)

    candidates = yaml.safe_load((output_dir / "internal_skill_candidates.yml").read_text(encoding="utf-8"))
    candidate = candidates["candidates"][0]
    assert candidate["safety"]["source_code_copied"] is False
    assert candidate["safety"]["license_review_required"] is True

    report = (output_dir / "p1_acceptance_report.md").read_text(encoding="utf-8")
    assert "# AgentLab P1 Closure Acceptance Report" in report
    assert "## Verdict\nPASS" in report
