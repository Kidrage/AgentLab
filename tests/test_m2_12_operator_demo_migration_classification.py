from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.m2_operator_demo import classify_migration_issue, run_m2_operator_demo

ROOT = Path(__file__).resolve().parents[1]


def test_private_infra_check_ids_are_deferred():
    for check_id in [
        "smb.truenas",
        "env.AGENTLAB_WEB_UI_TOKEN",
        "env.OPENAI_API_KEY",
        "env.DEEPSEEK_API_KEY",
        "env.DASHSCOPE_API_KEY",
        "env.GITHUB_TOKEN",
    ]:
        assert classify_migration_issue({"id": check_id, "status": "fail", "message": "missing"}) == "private_infra_deferred"


def test_core_missing_module_is_demo_blocking():
    assert classify_migration_issue({"id": "dir.agent_runtime", "status": "fail", "message": "agent_runtime missing"}) == "demo_blocking"


def test_warning_check_is_warning():
    assert classify_migration_issue({"id": "cache.root", "status": "warn", "message": "cache root not created yet"}) == "warning"


def test_ci_safe_demo_records_private_infra_without_blocking(tmp_path, monkeypatch):
    def fake_migration(agentlab_root, project="AgentLab", *, task_id=None, write_report=False, write_probe=True):
        return {
            "status": "fail",
            "summary": {"pass": 1, "warn": 0, "fail": 3},
            "checks": [
                {"id": "smb.truenas", "status": "fail", "message": "No SSH auth configured"},
                {"id": "env.DEEPSEEK_API_KEY", "status": "fail", "message": "DEEPSEEK_API_KEY missing"},
                {"id": "env.AGENTLAB_WEB_UI_TOKEN", "status": "fail", "message": "AGENTLAB_WEB_UI_TOKEN missing"},
            ],
            "blocking_reasons": ["No SSH auth configured", "DEEPSEEK_API_KEY missing", "AGENTLAB_WEB_UI_TOKEN missing"],
        }

    monkeypatch.setattr("agent_runtime.m2_operator_demo.run_migration_doctor", fake_migration)
    summary = run_m2_operator_demo(ROOT, tmp_path / "demo", project="AgentLab", strict_migration=False)

    assert summary["status"] == "pass"
    assert summary["migration"]["demo_blocking_failures"] == []
    assert len(summary["migration"]["private_infra_deferred_items"]) == 3
    assert summary["migration"]["strict_migration"] is False


def test_missing_core_file_remains_demo_blocking(tmp_path, monkeypatch):
    def fake_migration(agentlab_root, project="AgentLab", *, task_id=None, write_report=False, write_probe=True):
        return {
            "status": "fail",
            "summary": {"pass": 1, "warn": 0, "fail": 1},
            "checks": [
                {"id": "dir.agent_runtime", "status": "fail", "message": "agent_runtime missing"},
            ],
            "blocking_reasons": ["agent_runtime missing"],
        }

    monkeypatch.setattr("agent_runtime.m2_operator_demo.run_migration_doctor", fake_migration)
    summary = run_m2_operator_demo(ROOT, tmp_path / "demo", project="AgentLab", strict_migration=False)

    assert summary["status"] == "fail"
    assert summary["migration"]["demo_blocking_failures"][0]["id"] == "dir.agent_runtime"


def test_strict_migration_preserves_private_failures_as_blocking(tmp_path, monkeypatch):
    observed = {}

    def fake_migration(agentlab_root, project="AgentLab", *, task_id=None, write_report=False, write_probe=True):
        observed["write_probe"] = write_probe
        return {
            "status": "fail",
            "summary": {"pass": 1, "warn": 0, "fail": 1},
            "checks": [
                {"id": "smb.truenas", "status": "fail", "message": "No SSH auth configured"},
            ],
            "blocking_reasons": ["No SSH auth configured"],
        }

    monkeypatch.setattr("agent_runtime.m2_operator_demo.run_migration_doctor", fake_migration)
    summary = run_m2_operator_demo(ROOT, tmp_path / "demo", project="AgentLab", strict_migration=True)

    assert observed["write_probe"] is True
    assert summary["status"] == "fail"
    assert summary["migration"]["demo_blocking_failures"][0]["id"] == "smb.truenas"
    assert summary["migration"]["strict_migration"] is True


def test_summary_yaml_contains_classification_keys(tmp_path, monkeypatch):
    def fake_migration(agentlab_root, project="AgentLab", *, task_id=None, write_report=False, write_probe=True):
        return {
            "status": "warn",
            "summary": {"pass": 1, "warn": 1, "fail": 0},
            "checks": [
                {"id": "cache.root", "status": "warn", "message": "cache root not created yet"},
            ],
            "blocking_reasons": [],
        }

    monkeypatch.setattr("agent_runtime.m2_operator_demo.run_migration_doctor", fake_migration)
    out = tmp_path / "demo"
    run_m2_operator_demo(ROOT, out, project="AgentLab")
    summary = yaml.safe_load((out / "m2_operator_demo_summary.yml").read_text(encoding="utf-8"))

    assert "demo_blocking_failures" in summary["migration"]
    assert "private_infra_deferred_items" in summary["migration"]
    assert "warnings" in summary["migration"]
    assert "strict_migration" in summary["migration"]
    assert summary["migration"]["warnings"][0]["id"] == "cache.root"


def test_report_renders_deferred_private_infra_section(tmp_path, monkeypatch):
    def fake_migration(agentlab_root, project="AgentLab", *, task_id=None, write_report=False, write_probe=True):
        return {
            "status": "fail",
            "summary": {"pass": 1, "warn": 0, "fail": 1},
            "checks": [
                {"id": "smb.truenas", "status": "fail", "message": "No SSH auth configured"},
            ],
            "blocking_reasons": ["No SSH auth configured"],
        }

    monkeypatch.setattr("agent_runtime.m2_operator_demo.run_migration_doctor", fake_migration)
    out = tmp_path / "demo"
    run_m2_operator_demo(ROOT, out, project="AgentLab")
    report = (out / "M2_OPERATOR_OS_EXECUTION_ECONOMY_REPORT.md").read_text(encoding="utf-8")

    assert "## Migration Readiness vs Demo Acceptance" in report
    assert "deferred `smb.truenas`" in report
    assert "--strict-migration" in report
