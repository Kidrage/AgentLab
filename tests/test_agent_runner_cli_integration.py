"""Tests for agent_runner CLI executor dispatch integration.

These tests prove that ``run_agent_model`` in ``agent_runner.py`` actually
dispatches through the CLI executor before falling back to the direct API path.

No real subprocess is spawned — ``run_cli_agent`` and ``generate_text`` are
mocked so the dispatch logic is tested in isolation.
"""

from __future__ import annotations

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
        "cli_command": "hermes --task {task_packet_path}",
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


# ── Config profile tests ───────────────────────────────────────────────────


class TestConfigProfiles:
    """Verify config/agent_model_profiles.yml has required profiles."""

    def test_has_cli_supervisor_profile(self):
        """At least one profile has CLI-backed supervisor."""
        import yaml

        config_path = Path(__file__).parent.parent / "config" / "agent_model_profiles.yml"
        data = yaml.safe_load(config_path.read_text())
        profiles = data.get("profiles", {})

        cli_supervisors = []
        for name, profile in profiles.items():
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
        profiles = data.get("profiles", {})

        cli_coders = []
        for name, profile in profiles.items():
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
        profiles = data.get("profiles", {})

        direct_api_profiles = []
        for name, profile in profiles.items():
            all_direct = all(
                role.get("executor_type") == "direct_api"
                for role in profile.values()
                if isinstance(role, dict) and "executor_type" in role
            )
            if all_direct and profile:
                direct_api_profiles.append(name)

        assert direct_api_profiles, "No direct API-only profile found"
        print(f"Direct API-only profiles: {direct_api_profiles}")

    def test_four_required_profiles_exist(self):
        """Config has balanced, low_cost, direct_api_only, hybrid_agent_executor."""
        import yaml

        config_path = Path(__file__).parent.parent / "config" / "agent_model_profiles.yml"
        data = yaml.safe_load(config_path.read_text())
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

    PRIVATE_IPS = ["10.147.17.61", "10.147.17.250"]
    PRIVATE_PORTS = ["2222"]

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
            for ip in self.PRIVATE_IPS:
                if ip in content:
                    violations.append(f"{fname}: contains {ip}")
        assert not violations, f"Private IPs found: {violations}"

    def test_public_docs_no_private_ports(self):
        """No public-facing doc contains private SSH port."""
        root = Path(__file__).parent.parent
        violations = []
        for fname in self.PUBLIC_FILES:
            fpath = root / fname
            if not fpath.exists():
                continue
            content = fpath.read_text()
            for port in self.PRIVATE_PORTS:
                if f":{port}" in content or f" -p {port}" in content or f"-p{port}" in content:
                    violations.append(f"{fname}: contains port {port}")
        assert not violations, f"Private ports found: {violations}"
