"""Tests for agent_runner CLI executor dispatch integration.

These tests prove that ``run_agent_model`` in ``agent_runner.py`` actually
dispatches through the CLI executor before falling back to the direct API path.

No real subprocess is spawned — ``run_cli_agent`` and ``generate_text`` are
mocked so the dispatch logic is tested in isolation.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Make agent_runtime/ importable
sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))

from schemas import AgentRoute, LLMCallResult, WorkflowPlan  # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_plan(tmp_path: Path, budget_mode: str = "balanced") -> WorkflowPlan:
    """Build a minimal WorkflowPlan for testing."""
    route = AgentRoute(task_size="small", agents=["Supervisor", "Coder"])
    return WorkflowPlan(
        project="TestProject",
        task_id="task_test_001",
        agentlab_root=str(tmp_path),
        project_root=str(tmp_path / "projects" / "TestProject"),
        repo_path=str(tmp_path / "projects" / "TestProject"),
        run_dir=str(tmp_path / "projects" / "TestProject" / "runs" / "task_test_001"),
        user_request_path=str(
            tmp_path / "projects" / "TestProject" / "runs" / "task_test_001" / "user_request.md"
        ),
        budget_mode=budget_mode,
        route=route,
    )


def _cli_role_profile() -> dict:
    """Return a minimal CLI-backed supervisor profile."""
    return {
        "executor_type": "cli_agent",
        "cli_agent": "hermes",
        "cli_command": 'hermes -z "You are an AgentLab CLI executor. Read the JSON task packet at {task_packet_path}, perform the requested AgentLab role work, and return a concise markdown report with findings, actions taken, verification, and blockers."',
        "default": "deepseek_v4_pro",
    }


def _cli_success_result() -> LLMCallResult:
    """Return a simulated successful CLI LLMCallResult."""
    return LLMCallResult(
        provider="agentlab-cli-executor",
        model="hermes",
        content="# Supervisor Report (CLI)\n\nAll good.",
        status="completed",
    )


def _cli_not_available() -> object:
    """Return a CliAgentNotAvailable sentinel."""
    from cli_executor import CliAgentNotAvailable

    return CliAgentNotAvailable(
        cli_agent="hermes",
        reason="binary_not_found",
        detail="hermes not in PATH",
    )


def _api_fallback_result() -> LLMCallResult:
    """Return a simulated API fallback LLMCallResult."""
    return LLMCallResult(
        provider="deepseek",
        model="deepseek_v4_flash",
        content="# Supervisor Report (API fallback)\n\nAll good via API.",
        status="completed",
    )


# ── Tests ──────────────────────────────────────────────────────────────────


class TestAgentRunnerCliDispatch:
    """Prove that run_agent_model dispatches CLI executor correctly."""

    def test_calls_cli_agent_when_profile_is_cli_backed(self, tmp_path, monkeypatch):
        """run_agent_model calls run_cli_agent when the role profile resolves to CLI."""
        from cli_executor import CliAgentNotAvailable

        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)

        monkeypatch.setattr(
            "agent_runner.load_agentlab_configs",
            lambda _: {
                "agent_model_profiles": {
                    "profiles": {
                        "balanced": {
                            "supervisor": _cli_role_profile(),
                        },
                    },
                },
                "agent_registry": {"agents": {}},
                "model_providers": {"providers": {}, "defaults": {}},
                "model_profiles": {"profiles": {}},
                "model_catalog": {},
            },
        )
        monkeypatch.setattr(
            "operational_uploader.maybe_run_operational_agent",
            lambda *a, **kw: None,
        )
        # Patch resolve_agent_settings to avoid needing full config
        monkeypatch.setattr(
            "agent_runner.resolve_agent_settings",
            lambda *a, **kw: (
                SimpleNamespace(
                    provider="deepseek",
                    provider_type="openai_compatible",
                    model="deepseek_v4_flash",
                    base_url=None,
                    api_key_configured=False,
                    temperature=0.2,
                    top_p=1.0,
                    max_output_tokens=2000,
                    profile_name="",
                ),
                {},
            ),
        )
        monkeypatch.setattr(
            "agent_runner.compose_agent_messages",
            lambda *a, **kw: [{"role": "user", "content": "test"}],
        )
        monkeypatch.setattr(
            "brain_governor.evaluate_token_status",
            lambda *a, **kw: {},
        )

        # Scenario A: CLI agent succeeds
        with patch(
            "agent_runner.run_cli_agent",
            return_value=_cli_success_result(),
        ) as mock_cli, patch(
            "agent_runner.generate_text",
            return_value=_api_fallback_result(),
        ) as mock_api:
            from agent_runner import run_agent_model

            output = run_dir / "test_output.md"
            result = run_agent_model(tmp_path, plan, "Supervisor", output, apply_patches=False)

            mock_cli.assert_called_once()
            mock_api.assert_not_called()
            assert result.status == "completed"
            assert result.provider == "agentlab-cli-executor"
            assert "CLI" in result.content

    def test_falls_back_to_api_when_cli_not_available(self, tmp_path, monkeypatch):
        """run_agent_model falls back to generate_text when CliAgentNotAvailable."""
        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)

        monkeypatch.setattr(
            "agent_runner.load_agentlab_configs",
            lambda _: {
                "agent_model_profiles": {
                    "profiles": {
                        "balanced": {
                            "supervisor": _cli_role_profile(),
                        },
                    },
                },
                "agent_registry": {"agents": {}},
                "model_providers": {"providers": {}, "defaults": {}},
                "model_profiles": {"profiles": {}},
                "model_catalog": {},
            },
        )
        monkeypatch.setattr(
            "operational_uploader.maybe_run_operational_agent",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "agent_runner.resolve_agent_settings",
            lambda *a, **kw: (
                SimpleNamespace(
                    provider="deepseek",
                    provider_type="openai_compatible",
                    model="deepseek_v4_flash",
                    base_url=None,
                    api_key_configured=False,
                    temperature=0.2,
                    top_p=1.0,
                    max_output_tokens=2000,
                    profile_name="",
                ),
                {},
            ),
        )
        monkeypatch.setattr(
            "agent_runner.compose_agent_messages",
            lambda *a, **kw: [{"role": "user", "content": "test"}],
        )
        monkeypatch.setattr(
            "brain_governor.evaluate_token_status",
            lambda *a, **kw: {},
        )

        with patch(
            "agent_runner.run_cli_agent",
            return_value=_cli_not_available(),
        ) as mock_cli, patch(
            "agent_runner.generate_text",
            return_value=_api_fallback_result(),
        ) as mock_api:
            from agent_runner import run_agent_model

            output = run_dir / "test_output.md"
            result = run_agent_model(tmp_path, plan, "Supervisor", output, apply_patches=False)

            mock_cli.assert_called_once()
            mock_api.assert_called_once()
            assert result.status == "completed"
            assert "API fallback" in result.content

    def test_no_cli_dispatch_for_direct_api_only_profile(self, tmp_path, monkeypatch):
        """run_agent_model skips CLI dispatch when profile is direct_api_only."""
        plan = _make_plan(tmp_path, budget_mode="direct_api_only")
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)

        monkeypatch.setattr(
            "agent_runner.load_agentlab_configs",
            lambda _: {
                "agent_model_profiles": {
                    "profiles": {
                        "direct_api_only": {
                            "supervisor": {
                                "executor_type": "direct_api",
                                "default": "deepseek_v4_pro",
                            },
                        },
                    },
                },
                "agent_registry": {"agents": {}},
                "model_providers": {"providers": {}, "defaults": {}},
                "model_profiles": {"profiles": {}},
                "model_catalog": {},
            },
        )
        monkeypatch.setattr(
            "operational_uploader.maybe_run_operational_agent",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "agent_runner.resolve_agent_settings",
            lambda *a, **kw: (
                SimpleNamespace(
                    provider="deepseek",
                    provider_type="openai_compatible",
                    model="deepseek_v4_pro",
                    base_url=None,
                    api_key_configured=False,
                    temperature=0.2,
                    top_p=1.0,
                    max_output_tokens=2000,
                    profile_name="",
                ),
                {},
            ),
        )
        monkeypatch.setattr(
            "agent_runner.compose_agent_messages",
            lambda *a, **kw: [{"role": "user", "content": "test"}],
        )
        monkeypatch.setattr(
            "brain_governor.evaluate_token_status",
            lambda *a, **kw: {},
        )

        with patch(
            "agent_runner.run_cli_agent",
            return_value=_cli_success_result(),
        ) as mock_cli, patch(
            "agent_runner.generate_text",
            return_value=_api_fallback_result(),
        ) as mock_api:
            from agent_runner import run_agent_model

            output = run_dir / "test_output.md"
            result = run_agent_model(tmp_path, plan, "Supervisor", output, apply_patches=False)

            mock_cli.assert_not_called()
            mock_api.assert_called_once()
            assert result.status == "completed"

    def test_no_real_subprocess_in_tests(self):
        """Sanity: this test file never executes real subprocess calls."""
        # Check that the test file doesn't actually import subprocess to run things
        # (it's fine to mention "subprocess.run" in comments/docstrings)
        import ast

        source = Path(__file__).read_text()
        tree = ast.parse(source)
        has_subprocess_import = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "subprocess":
                        has_subprocess_import = True
            elif isinstance(node, ast.ImportFrom):
                if node.module == "subprocess":
                    has_subprocess_import = True
        assert not has_subprocess_import, (
            "test file must not import subprocess — use mocks via patch()"
        )


def _iter_config_role_groups(data: dict):
    """Yield named role groups from legacy profiles and schema-v4 modes/tiers."""
    for name, profile in (data.get("profiles", {}) or {}).items():
        yield name, profile
    for mode_name, mode in (data.get("modes", {}) or {}).items():
        for tier_name, tier in ((mode or {}).get("tiers", {}) or {}).items():
            yield f"{mode_name}.{tier_name}", tier or {}


# ── Schema v4 dispatch tests ──────────────────────────────────────────────


def _schema_v4_configs() -> dict:
    """Return a minimal config set with schema v4 agent_model_profiles."""
    return {
        "agent_model_profiles": {
            "schema_version": 4.0,
            "default_mode": "full_cli",
            "modes": {
                "full_cli": {
                    "tiers": {
                        "full": {
                            "supervisor": {
                                "executor_type": "cli_agent",
                                "cli_agent": "hermes",
                                "cli_command": 'hermes -z "Read {task_packet_path}"',
                                "default": "deepseek_v4_pro",
                            },
                        },
                    },
                },
            },
        },
        "agent_registry": {"agents": {}},
        "model_providers": {"providers": {}, "defaults": {}},
        "model_profiles": {"profiles": {}},
        "model_catalog": {},
    }


class TestAgentRunnerSchemaV4Dispatch:
    """Prove agent_runner dispatches CLI for schema v4 configs."""

    def test_cli_attempted_before_api_for_schema_v4(self, tmp_path, monkeypatch):
        """With schema v4 full_cli/full/supervisor, run_cli_agent is called before API."""
        plan = _make_plan(tmp_path, budget_mode="full")
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)

        monkeypatch.setattr(
            "agent_runner.load_agentlab_configs",
            lambda _: _schema_v4_configs(),
        )
        monkeypatch.setattr(
            "operational_uploader.maybe_run_operational_agent",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "agent_runner.resolve_agent_settings",
            lambda *a, **kw: (
                SimpleNamespace(
                    provider="deepseek", provider_type="openai_compatible",
                    model="deepseek_v4_pro", base_url=None,
                    api_key_configured=False, temperature=0.2, top_p=1.0,
                    max_output_tokens=2000, profile_name="",
                ),
                {},
            ),
        )
        monkeypatch.setattr(
            "agent_runner.compose_agent_messages",
            lambda *a, **kw: [{"role": "user", "content": "test"}],
        )
        monkeypatch.setattr(
            "brain_governor.evaluate_token_status",
            lambda *a, **kw: {},
        )

        with patch(
            "agent_runner.run_cli_agent",
            return_value=_cli_success_result(),
        ) as mock_cli, patch(
            "agent_runner.generate_text",
            return_value=_api_fallback_result(),
        ) as mock_api:
            from agent_runner import run_agent_model

            output = run_dir / "test_output.md"
            result = run_agent_model(tmp_path, plan, "Supervisor", output, apply_patches=False)

            mock_cli.assert_called_once()
            mock_api.assert_not_called()
            assert result.status == "completed"
            # Audit metadata must show CLI was used
            assert result.raw_usage.get("usage_source") == "cli_agent"
            assert result.raw_usage.get("executor_type") == "cli_agent"
            assert result.raw_usage.get("api_fallback_used") is False
            assert result.raw_usage.get("resolved_schema") == "modes_v4"

    def test_cli_unavailable_produces_api_fallback_with_metadata(self, tmp_path, monkeypatch):
        """When CLI is unavailable, API fallback records reason in result metadata."""
        plan = _make_plan(tmp_path, budget_mode="full")
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)

        monkeypatch.setattr(
            "agent_runner.load_agentlab_configs",
            lambda _: _schema_v4_configs(),
        )
        monkeypatch.setattr(
            "operational_uploader.maybe_run_operational_agent",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "agent_runner.resolve_agent_settings",
            lambda *a, **kw: (
                SimpleNamespace(
                    provider="deepseek", provider_type="openai_compatible",
                    model="deepseek_v4_pro", base_url=None,
                    api_key_configured=False, temperature=0.2, top_p=1.0,
                    max_output_tokens=2000, profile_name="",
                ),
                {},
            ),
        )
        monkeypatch.setattr(
            "agent_runner.compose_agent_messages",
            lambda *a, **kw: [{"role": "user", "content": "test"}],
        )
        monkeypatch.setattr(
            "brain_governor.evaluate_token_status",
            lambda *a, **kw: {},
        )

        with patch(
            "agent_runner.run_cli_agent",
            return_value=_cli_not_available(),
        ) as mock_cli, patch(
            "agent_runner.generate_text",
            return_value=_api_fallback_result(),
        ) as mock_api:
            from agent_runner import run_agent_model

            output = run_dir / "test_output.md"
            result = run_agent_model(tmp_path, plan, "Supervisor", output, apply_patches=False)

            mock_cli.assert_called_once()
            mock_api.assert_called_once()
            assert result.status == "completed"
            # Audit metadata must document the CLI→API fallback
            assert result.raw_usage.get("usage_source") == "api_usage"
            assert result.raw_usage.get("executor_type") == "cli_agent_fallback"
            assert result.raw_usage.get("api_fallback_used") is True
            assert result.raw_usage.get("configured_cli_agent") == "hermes"
            assert "binary_not_found" in str(result.raw_usage.get("fallback_reason", ""))


# ── Config profile tests ───────────────────────────────────────────────────


class TestConfigProfiles:
    """Verify config/agent_model_profiles.yml has required profiles."""

    def test_has_cli_supervisor_profile(self):
        """At least one profile has CLI-backed supervisor."""
        import yaml

        config_path = Path(__file__).parent.parent / "config" / "agent_model_profiles.yml"
        data = yaml.safe_load(config_path.read_text())
        cli_supervisors = []
        for name, profile in _iter_config_role_groups(data):
            sup = profile.get("supervisor", {})
            if sup.get("executor_type") == "cli_agent":
                cli_supervisors.append(name)

        assert cli_supervisors, "No profile has CLI-backed supervisor"
        print(f"CLI-backed supervisor profiles: {cli_supervisors}")

    def test_has_cli_coder_profile(self):
        """At least one profile has CLI-backed coder."""
        import yaml

        config_path = Path(__file__).parent.parent / "config" / "agent_model_profiles.yml"
        data = yaml.safe_load(config_path.read_text())
        cli_coders = []
        for name, profile in _iter_config_role_groups(data):
            coder = profile.get("coder", {})
            if coder.get("executor_type") == "cli_agent":
                cli_coders.append(name)

        assert cli_coders, "No profile has CLI-backed coder"
        print(f"CLI-backed coder profiles: {cli_coders}")

    def test_has_direct_api_only_profile(self):
        """At least one profile is entirely direct_api."""
        import yaml

        config_path = Path(__file__).parent.parent / "config" / "agent_model_profiles.yml"
        data = yaml.safe_load(config_path.read_text())
        direct_api_profiles = []
        for name, profile in _iter_config_role_groups(data):
            all_direct = all(
                role.get("executor_type") == "direct_api"
                for role in profile.values()
                if isinstance(role, dict) and "executor_type" in role
            )
            if all_direct and profile:
                direct_api_profiles.append(name)

        assert direct_api_profiles, "No direct API-only profile found"
        print(f"Direct API-only profiles: {direct_api_profiles}")

    def test_required_execution_modes_exist(self):
        """Config has the schema-v4 execution modes or legacy named profiles."""
        import yaml

        config_path = Path(__file__).parent.parent / "config" / "agent_model_profiles.yml"
        data = yaml.safe_load(config_path.read_text())
        if "modes" in data:
            required = {"full_cli", "full_api", "hybrid_ide"}
            missing = required - set((data.get("modes", {}) or {}).keys())
            assert not missing, f"Missing modes: {missing}"
            return

        profiles = data.get("profiles", {})
        required = {"balanced", "low_cost", "direct_api_only", "hybrid_agent_executor"}
        missing = required - set(profiles.keys())
        assert not missing, f"Missing profiles: {missing}"
        print(f"All required profiles present: {sorted(required)}")


# ── Text integrity tests ───────────────────────────────────────────────────


class TestTextIntegrityMinimums:
    """Verify key hotfix files meet minimum line counts."""

    def test_cli_executor_min_lines(self):
        path = Path(__file__).parent.parent / "agent_runtime" / "cli_executor.py"
        lines = path.read_text().split("\n")
        assert len(lines) >= 120, f"cli_executor.py has {len(lines)} lines, need >= 120"

    def test_agent_runner_min_lines(self):
        path = Path(__file__).parent.parent / "agent_runtime" / "agent_runner.py"
        lines = path.read_text().split("\n")
        assert len(lines) >= 120, f"agent_runner.py has {len(lines)} lines, need >= 120"

    def test_test_cli_executor_min_lines(self):
        path = Path(__file__).parent.parent / "tests" / "test_cli_executor.py"
        lines = path.read_text().split("\n")
        assert len(lines) >= 100, f"test_cli_executor.py has {len(lines)} lines, need >= 100"

    def test_config_agent_model_profiles_min_lines(self):
        path = Path(__file__).parent.parent / "config" / "agent_model_profiles.yml"
        lines = path.read_text().split("\n")
        assert len(lines) >= 80, f"agent_model_profiles.yml has {len(lines)} lines, need >= 80"

    def test_agents_md_min_lines(self):
        path = Path(__file__).parent.parent / "AGENTS.md"
        lines = path.read_text().split("\n")
        assert len(lines) >= 80, f"AGENTS.md has {len(lines)} lines, need >= 80"

    def test_operating_model_md_min_lines(self):
        path = Path(__file__).parent.parent / "OPERATING_MODEL.md"
        lines = path.read_text().split("\n")
        assert len(lines) >= 80, f"OPERATING_MODEL.md has {len(lines)} lines, need >= 80"


# ── Public doc IP sanitization tests ───────────────────────────────────────


class TestPublicDocSanitization:
    """Verify public docs do not contain private network IPs or ports."""

    # Regex patterns that match private/leaked IPs and ports in public docs.
    # Concrete IPs must never appear in tracking; use generic patterns instead.
    PRIVATE_IP_RE = re.compile(r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b")
    # Check for non-standard SSH ports (e.g. :2222) in docs
    PRIVATE_PORT_RE = re.compile(r":(?:2[2-9]\d\d|[3-9]\d{3,})\b|\s-p\s*(?:2[2-9]\d\d|[3-9]\d{3,})\b")

    PUBLIC_FILES = [
        "README.md",
        "AGENTS.md",
        "OPERATING_MODEL.md",
        "DRIVER_PROTOCOL.md",
    ]

    def test_public_docs_no_private_ips(self):
        """No public-facing doc contains private IP addresses."""
        root = Path(__file__).parent.parent
        violations = []
        for fname in self.PUBLIC_FILES:
            fpath = root / fname
            if not fpath.exists():
                continue
            content = fpath.read_text()
            if self.PRIVATE_IP_RE.search(content):
                violations.append(f"{fname}: contains private IP pattern")
        assert not violations, f"Private IPs found: {violations}"

    def test_public_docs_no_private_ports(self):
        """No public-facing doc contains non-standard SSH port."""
        root = Path(__file__).parent.parent
        violations = []
        for fname in self.PUBLIC_FILES:
            fpath = root / fname
            if not fpath.exists():
                continue
            content = fpath.read_text()
            if self.PRIVATE_PORT_RE.search(content):
                violations.append(f"{fname}: contains private port pattern")
        assert not violations, f"Private ports found: {violations}"
