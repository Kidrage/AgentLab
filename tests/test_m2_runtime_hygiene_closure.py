"""M2 Runtime Hygiene Closure tests.

Validates:
- Secret redaction in config output
- furgal/frugal spelling consistency
- Config CLI behavior for secret values
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _agentlab(*args: str) -> subprocess.CompletedProcess:
    """Run ./agentlab.sh with the given arguments."""
    return subprocess.run(
        ["./agentlab.sh", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )


# ── Secret redaction tests ───────────────────────────────────────────────


def test_config_get_redacts_secret_values() -> None:
    """config-get for a secret-keyed value should show ***REDACTED***."""
    result = _agentlab("config", "config-get", "--key", "model_providers.deepseek_api_key")
    output = result.stdout + result.stderr
    assert "***REDACTED***" in output or "Is Secret:  true" in output, \
        f"Expected redaction, got: {output[:500]}"


def test_config_list_redacts_secret_values() -> None:
    """config-list output should redact secret values."""
    result = _agentlab("config", "config-list", "--limit", "100")
    output = result.stdout + result.stderr
    assert "sk-" not in output, f"Raw API key prefix found in output: {output[:200]}"


def test_config_output_does_not_leak_env_values() -> None:
    """config output should not leak environment variable values."""
    result = _agentlab("config", "config-get", "--key", "model_providers.deepseek_api_key")
    output = result.stdout + result.stderr
    assert any(marker in output for marker in ["***REDACTED***", "<none>", "not found"]), \
        f"Expected redacted/none/not-found, got: {output[:300]}"


# ── Spelling consistency tests ───────────────────────────────────────────


def test_config_profiles_use_frugal_spelling() -> None:
    """config_profiles.yml must use 'frugal' not 'furgal'."""
    cp = ROOT / "config" / "config_profiles.yml"
    content = cp.read_text(encoding="utf-8")
    assert "furgal" not in content, f"'furgal' typo found in {cp}"
    assert "frugal" in content, f"'frugal' spelling not found in {cp}"


def test_config_center_schema_uses_frugal_spelling() -> None:
    """config_center.yml schema must use 'frugal' not 'furgal'."""
    cc = ROOT / "config" / "config_center.yml"
    content = cc.read_text(encoding="utf-8")
    assert "furgal" not in content, f"'furgal' typo found in {cc}"


def test_no_committed_config_uses_furgal() -> None:
    """No committed YAML config should contain 'furgal'."""
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "grep", "furgal", "--", "*.yml", "*.yaml"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            pytest.fail(f"Found 'furgal' in tracked YAML files:\n{result.stdout}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # If git unavailable, do a manual check on known config files
        config_dir = ROOT / "config"
        for yf in config_dir.glob("*.yml"):
            if "furgal" in yf.read_text(encoding="utf-8"):
                pytest.fail(f"'furgal' found in {yf}")


# ── Config CLI behavior ──────────────────────────────────────────────────


def test_config_validate_exits_zero() -> None:
    """config-validate should exit 0 on default config."""
    result = _agentlab("config", "config-validate")
    assert result.returncode == 0, f"config-validate failed: {result.stderr[:500]}"


def test_config_list_does_not_silently_truncate() -> None:
    """config-list with --all should not truncate."""
    result = _agentlab("config", "config-list", "--all")
    output = result.stdout + result.stderr
    # With --all, should NOT show "Showing X of Y" truncation message
    assert "Showing" not in output or "of" not in output, \
        f"Truncation message found in --all output: {output[:300]}"


def test_config_list_reports_truncation_when_limit_applied() -> None:
    """config-list with --limit should report truncation."""
    result = _agentlab("config", "config-list", "--limit", "10")
    output = result.stdout + result.stderr
    assert "Showing 10 of" in output, \
        f"Expected truncation message, got: {output[:300]}"


def test_config_get_missing_key_fails_cleanly() -> None:
    """config-get for nonexistent key should exit non-zero with clear message."""
    result = _agentlab("config", "config-get", "--key", "nonexistent.ghost.key")
    assert result.returncode != 0
    assert "not found" in (result.stdout + result.stderr).lower()


def test_config_get_routing_policy_default_budget() -> None:
    """config-get routing_policy.default_budget works."""
    result = _agentlab("config", "config-get", "--key", "routing_policy.default_budget")
    assert result.returncode == 0
    assert "balanced" in result.stdout


def test_config_get_budget_policy_fields() -> None:
    """config-get budget_policy.max_task_cost_usd resolves without double namespace."""
    result = _agentlab("config", "config-get", "--key", "budget_policy.max_task_cost_usd")
    assert result.returncode == 0
    assert "0.2" in result.stdout


# ── CLI no-secret-leak verification ──────────────────────────────────────


def test_no_real_secrets_appear_in_config_list_output() -> None:
    """Sanity check: config-list output should not contain common secret patterns."""
    result = _agentlab("config", "config-list", "--all")
    output = result.stdout
    # Common API key prefixes that should NEVER appear
    forbidden_prefixes = [
        "sk-ant-",   # Anthropic
        "sk-",        # OpenAI / generic
        "dashscope-", # DashScope
    ]
    for prefix in forbidden_prefixes:
        if prefix in output and f"_{prefix}" not in output:
            pytest.fail(f"Potential secret leak: '{prefix}' found in config-list output")
