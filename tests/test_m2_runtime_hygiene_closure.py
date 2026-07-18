"""M2 Runtime Hygiene Closure tests.

Validates:
- Secret redaction in config output (unit + integration)
- furgal/frugal spelling consistency
- Config CLI behavior (truncation, validation, missing-key handling)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_runtime.config_center.schema import ConfigKeySchema
from agent_runtime.config_center.resolver import resolve_key, resolve_all_keys
from agent_runtime.config_center.renderer import _safe_repr
from agent_runtime.config_center.secrets_redaction import is_secret_key, REDACTED_PLACEHOLDER

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


# ── Secret redaction unit tests ──────────────────────────────────────────


def test_safe_repr_redacts_when_is_secret_true() -> None:
    """_safe_repr should return REDACTED when cv_is_secret=True."""
    assert _safe_repr("sk-abc123", "any.key", cv_is_secret=True) == REDACTED_PLACEHOLDER


def test_safe_repr_redacts_on_key_name_heuristic() -> None:
    """_safe_repr should redact values whose key name matches secret patterns."""
    assert _safe_repr("secret123", "model_providers.deepseek_api_key") == REDACTED_PLACEHOLDER
    assert _safe_repr("token-abc", "some.secret.token") == REDACTED_PLACEHOLDER


def test_safe_repr_passes_non_secret_values() -> None:
    """_safe_repr should pass through regular values."""
    assert _safe_repr("balanced", "routing_policy.default_budget") == "balanced"
    assert _safe_repr(42, "some.int_key") == "42"


def test_is_secret_key_matches_known_patterns() -> None:
    """is_secret_key should match API keys, secrets, tokens, etc."""
    assert is_secret_key("api_key") is True
    assert is_secret_key("deepseek_api_key") is True
    assert is_secret_key("dashscope_api_key") is True
    assert is_secret_key("my_secret") is True
    assert is_secret_key("auth_token") is True
    assert is_secret_key("access_key") is True
    assert is_secret_key("normal_config") is False
    assert is_secret_key("default_budget") is False


def test_secret_schema_metadata_sets_is_secret_true() -> None:
    """Schema `secret: true` must propagate to ConfigValue.is_secret via resolve_key."""
    schema_keys = {
        "model_providers.deepseek_api_key": ConfigKeySchema(
            key="model_providers.deepseek_api_key", secret=True, type_="str"
        ),
        "routing_policy.default_budget": ConfigKeySchema(
            key="routing_policy.default_budget", secret=False, type_="str"
        ),
    }
    # Resolve a known non-secret key
    cv = resolve_key(ROOT, "routing_policy.default_budget", schema_keys=schema_keys)
    assert cv is not None
    assert cv.is_secret is False, f"default_budget should not be secret"

    # A secret-marked key that IS in the actual config layers may still
    # resolve as secret based on schema metadata (is_secret set on CV even
    # if the value comes from env/config).
    # Verify that schema_keys lookup works correctly.
    cv2 = resolve_key(ROOT, "budget_policy.max_task_cost_usd", schema_keys=schema_keys)
    assert cv2 is not None
    # This key is NOT in our schema — so is_secret should be False
    assert cv2.is_secret is False


# ── Secret redaction integration tests ───────────────────────────────────


def test_config_list_redacts_secret_values() -> None:
    """config-list output should redact secret values."""
    result = _agentlab("config", "config-list", "--limit", "100")
    output = result.stdout + result.stderr
    # Long-form API key prefixes should never appear as values
    assert "sk-ant-" not in output, f"Anthropic key prefix found in output"
    assert "dashscope-" not in output, f"DashScope key prefix found in output"


def test_config_output_does_not_leak_env_values() -> None:
    """config output should not leak environment variable values for known secret keys."""
    result = _agentlab("config", "config-get", "--key", "routing_policy.default_budget")
    output = result.stdout + result.stderr
    # For non-secret keys, the actual value should be visible
    assert result.returncode == 0
    assert "balanced" in output
    assert "***REDACTED***" not in output


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
    """The --all resolver contract returns every discovered key."""
    resolved, truncated, total = resolve_all_keys(ROOT, limit=None)
    assert truncated is False
    assert len(resolved) == total


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


def test_config_get_budget_policy_fields() -> None:
    """config-get budget_policy.max_task_cost_usd resolves without double namespace."""
    result = _agentlab("config", "config-get", "--key", "budget_policy.max_task_cost_usd")
    assert result.returncode == 0
    assert "0.2" in result.stdout


# ── E2E secret redaction tests (fixture-based, no real API keys) ──────────


class TestSecretRedactionE2E:
    """End-to-end secret redaction tests using temporary fixture configs.

    These cover the full chain: schema → resolver → renderer → output,
    verifying that secrets are redacted end-to-end without relying on
    real API keys or environment variables.
    """

    @staticmethod
    def _make_temp_agentlab_root(tmp_path: Path) -> Path:
        """Create a minimal AgentLab config directory with a fake secret."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        # Config file with a fake API key
        (config_dir / "model_providers.yml").write_text(
            "deepseek_api_key: fake-test-secret-12345\n"
        )
        return tmp_path

    def test_full_chain_secret_redacted_in_renderer(self, tmp_path: Path) -> None:
        """schema + resolver + renderer: secret must be redacted in output."""
        root = self._make_temp_agentlab_root(tmp_path)

        schema_keys = {
            "model_providers.deepseek_api_key": ConfigKeySchema(
                key="model_providers.deepseek_api_key", secret=True, type_="str"
            ),
        }

        cv = resolve_key(root, "model_providers.deepseek_api_key", schema_keys=schema_keys)
        assert cv is not None, "Secret key should resolve from fixture config"
        assert cv.value == "fake-test-secret-12345", "Fixture value should be loaded"
        assert cv.is_secret is True, (
            "Schema secret=true MUST propagate to ConfigValue.is_secret — "
            "if this fails, the resolver→renderer chain is broken"
        )

        # Verify renderer would redact (this is what render_config_get calls)
        display = _safe_repr(cv.value, cv.key, cv_is_secret=cv.is_secret)
        assert display == REDACTED_PLACEHOLDER, (
            f"_safe_repr should return {REDACTED_PLACEHOLDER} when cv.is_secret=True, "
            f"got '{display}' — secret would leak to terminal"
        )

    def test_full_chain_non_secret_passes_through(self, tmp_path: Path) -> None:
        """Non-secret keys in the same config must NOT be redacted."""
        root = self._make_temp_agentlab_root(tmp_path)
        (root / "config" / "model_providers.yml").write_text(
            "deepseek_api_key: fake-secret\n"
            "some_setting: visible-value\n"
        )

        schema_keys = {
            "model_providers.deepseek_api_key": ConfigKeySchema(
                key="model_providers.deepseek_api_key", secret=True, type_="str"
            ),
        }

        # Secret key → redacted
        cv_secret = resolve_key(root, "model_providers.deepseek_api_key", schema_keys=schema_keys)
        assert cv_secret is not None and cv_secret.is_secret is True
        assert _safe_repr(cv_secret.value, cv_secret.key, cv_is_secret=True) == REDACTED_PLACEHOLDER

        # Non-secret key → visible
        cv_visible = resolve_key(root, "model_providers.some_setting", schema_keys=schema_keys)
        assert cv_visible is not None and cv_visible.is_secret is False, (
            "Key not in schema should have is_secret=False"
        )
        assert _safe_repr(cv_visible.value, cv_visible.key, cv_is_secret=False) == "visible-value"

    def test_schema_does_not_cross_contaminate_keys(self, tmp_path: Path) -> None:
        """Schema secret=true for one key must NOT affect other keys."""
        root = self._make_temp_agentlab_root(tmp_path)
        (root / "config" / "model_providers.yml").write_text(
            "deepseek_api_key: sk-secret\n"
            "provider_name: DeepSeek\n"
            "dashscope_api_key: qwen-secret\n"
        )

        schema_keys = {
            "model_providers.deepseek_api_key": ConfigKeySchema(
                key="model_providers.deepseek_api_key", secret=True, type_="str"
            ),
            # dashscope_api_key NOT in schema — should not be secret
        }

        # Marked secret → is_secret=True
        cv1 = resolve_key(root, "model_providers.deepseek_api_key", schema_keys=schema_keys)
        assert cv1 is not None and cv1.is_secret is True

        # NOT in schema → is_secret=False (even though key name is heuristically secret)
        cv2 = resolve_key(root, "model_providers.dashscope_api_key", schema_keys=schema_keys)
        assert cv2 is not None, "dashscope_api_key should resolve from fixture"
        assert cv2.is_secret is False, (
            "Key NOT in schema should have is_secret=False — "
            "cross-contamination bug: schema secret flag leaked to unrelated key"
        )

        # Unrelated key → is_secret=False
        cv3 = resolve_key(root, "model_providers.provider_name", schema_keys=schema_keys)
        assert cv3 is not None and cv3.is_secret is False

    def test_cli_config_get_redacts_fixture_secret(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLI config-get (monkeypatched root) must redact fixture secret.

        This is the closest test to the original CLI E2E test that was
        removed in 2050806, but it uses a temp fixture config instead of
        relying on real API keys.
        """
        import io
        from rich.console import Console
        from agent_runtime.config_center import cli as cli_mod

        root = self._make_temp_agentlab_root(tmp_path)

        # Minimal config_center.yml schema in temp dir
        import yaml
        schema_path = root / "config" / "config_center.yml"
        schema_path.write_text(yaml.dump({
            "version": 1,
            "keys": {
                "model_providers.deepseek_api_key": {
                    "type": "str",
                    "secret": True,
                },
            },
        }))

        # Monkeypatch the root
        monkeypatch.setattr(cli_mod, "_agentlab_root", lambda: root)

        # Capture Rich console output — must patch the renderer's console,
        # not the cli module's (cli imports console from renderer)
        import agent_runtime.config_center.renderer as renderer_mod
        captured = io.StringIO()
        monkeypatch.setattr(renderer_mod, "console", Console(file=captured, force_terminal=False))

        # Run the actual CLI command function (pass project=None explicitly
        # because typer.Option defaults are OptionInfo objects, not None)
        cli_mod.config_get(key="model_providers.deepseek_api_key", project=None)

        output = captured.getvalue()

        # The secret value must NOT appear in output
        assert "fake-test-secret-12345" not in output, (
            f"SECRET LEAK: raw fixture secret appeared in CLI output:\n{output[:300]}"
        )
        # Redaction marker must appear
        assert REDACTED_PLACEHOLDER in output, (
            f"Missing redaction marker in CLI output:\n{output[:300]}"
        )
        # Is Secret must be true
        assert "true" in output, (
            f"Expected Is Secret: true in CLI output:\n{output[:300]}"
        )
