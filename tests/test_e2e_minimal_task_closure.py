from __future__ import annotations

import socket
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
E2E_DIR = ROOT / "acceptance_runs" / "e2e_minimal_task"

REQUIRED_ARTIFACTS = [
    "input_task.md",
    "init_task.yml",
    "task_plan.yml",
    "run_pipeline_dry_run.yml",
    "check.yml",
    "review_verdict.yml",
    "provider_feedback.yml",
    "router_feedback.yml",
    "revision_packet.md",
    "final_delivery_report.md",
]


def _artifact_texts() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in E2E_DIR.iterdir()
        if path.is_file()
    }


def _load_yaml(name: str) -> dict:
    data = yaml.safe_load((E2E_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict), name
    return data


def test_e2e_run_generates_required_artifacts() -> None:
    assert E2E_DIR.is_dir()
    for name in REQUIRED_ARTIFACTS:
        path = E2E_DIR / name
        assert path.is_file(), name
        assert path.read_text(encoding="utf-8").strip(), name


def test_review_verdict_is_valid_yaml() -> None:
    data = _load_yaml("review_verdict.yml")
    assert data["verdict"] in {"accepted", "needs_revision", "rejected"}
    assert data["task_id"] == "task_s4_minimal_e2e"


def test_provider_feedback_is_valid_yaml() -> None:
    data = _load_yaml("provider_feedback.yml")
    assert data["provider_id"] == "mock_provider"
    assert data["outcome"]["retry_recommended"] is False
    assert data["cost"]["real_api_calls"] is False


def test_router_feedback_is_valid_yaml() -> None:
    data = _load_yaml("router_feedback.yml")
    assert data["recommendation"] in {"neutral", "watchlist", "prefer", "quarantine"}
    assert data["router_apply"]["enabled"] is False
    assert data["router_apply"]["production_config_modified"] is False


def test_final_delivery_report_exists() -> None:
    text = (E2E_DIR / "final_delivery_report.md").read_text(encoding="utf-8")
    assert "# S4 Minimal E2E Final Delivery Report" in text
    assert "Accepted" in text


def test_artifacts_do_not_contain_local_absolute_paths() -> None:
    for name, text in _artifact_texts().items():
        assert "/Users/" not in text, name
        assert "/private/" not in text, name


def test_artifacts_do_not_reference_secrets() -> None:
    forbidden = ["BEGIN OPENSSH", "BEGIN RSA", "ghp_", "sk-"]
    for name, text in _artifact_texts().items():
        lowered = text.lower()
        for pattern in forbidden:
            assert pattern.lower() not in lowered, f"{name} references {pattern}"
    check = _load_yaml("check.yml")
    assert check["safety"]["secrets_read"] == "none"


def test_validation_does_not_open_network() -> None:
    def block_network(*_args, **_kwargs):
        raise AssertionError("network access is forbidden for S4 E2E validation")

    with patch.object(socket, "create_connection", side_effect=block_network):
        assert _load_yaml("run_pipeline_dry_run.yml")["external_api_calls"] is False


def test_router_apply_defaults_false() -> None:
    router = _load_yaml("router_feedback.yml")
    assert router["router_apply"]["enabled"] is False
    assert router["router_apply"]["mode"] == "dry_run"


def test_text_integrity_audit_covers_e2e_artifacts() -> None:
    from scripts.audit_text_integrity import run_audit

    audits = {audit.path: audit for audit in run_audit(ROOT)}
    for name in REQUIRED_ARTIFACTS:
        rel = f"acceptance_runs/e2e_minimal_task/{name}"
        assert rel in audits
        assert audits[rel].suspicious_single_line is False
