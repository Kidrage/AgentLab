import yaml
from pathlib import Path
from agent_runtime.workers.cli_command_policy import validate_cli_agent_profiles, DANGEROUS_FLAGS

def load_profiles():
    p = Path("config/agent_model_profiles.yml")
    return yaml.safe_load(p.read_text(encoding="utf-8"))

def test_agent_model_profiles_yaml_loads():
    data = load_profiles()
    assert data is not None

def test_default_profiles_do_not_use_dangerous_ccs_permission_skip():
    data = load_profiles()
    findings = validate_cli_agent_profiles(data)
    assert len(findings) == 0, f"Found safety violations: {findings}"

def test_trusted_headless_profile_does_not_override_global_bypass_ban():
    data = load_profiles()
    trusted = data.get("modes", {}).get("trusted_headless_cli")
    assert trusted is not None
    safety = trusted.get("safety", {})
    assert safety.get("requires_env", {}).get("AGENTLAB_ALLOW_DANGEROUS_CCS") == "1"
    assert safety.get("requires_human_approval") is True
    
    cmd = trusted["tiers"]["full"]["coder"]["cli_command"]
    assert not any(flag in cmd for flag in DANGEROUS_FLAGS)
    assert "--permission-mode plan" in cmd

def test_trusted_headless_profile_is_never_default():
    data = load_profiles()
    trusted = data.get("modes", {}).get("trusted_headless_cli")
    assert trusted.get("safety", {}).get("never_default") is True
    assert data.get("default_mode") != "trusted_headless_cli"

def test_all_claude_code_profiles_keep_approval_required():
    from agent_runtime.workers.detector import DEFAULT_CANDIDATES

    claude = next(c for c in DEFAULT_CANDIDATES if c["worker_id"] == "claude_code")
    assert claude.get("approval_required") is True
    assert claude.get("risk_level") == "high"
    assert claude.get("default_enabled") is False


def test_generic_claude_contract_can_execute_under_governed_auto_mode():
    contracts = yaml.safe_load(
        Path("config/worker_invocation_contracts.yml").read_text(encoding="utf-8")
    )["contracts"]

    generic = contracts["claude"]
    assert "--permission-mode auto" in generic["template"]
    assert "bypassPermissions" not in generic["template"]
    assert "--dangerously-skip-permissions" not in generic["template"]

    for contract_name in ("claude_writer", "claude_supervisor_fallback"):
        bounded = contracts[contract_name]["template"]
        assert "--permission-mode plan" in bounded
        assert '--tools ""' in bounded


def test_longform_governance_contract_is_read_only_and_route_bound():
    contracts = yaml.safe_load(
        Path("config/worker_invocation_contracts.yml").read_text(encoding="utf-8")
    )["contracts"]
    registry = yaml.safe_load(
        Path("config/runtime_registry.yml").read_text(encoding="utf-8")
    )

    template = contracts["claude_longform_governance"]["template"]
    assert "--permission-mode plan" in template
    assert "--permission-mode auto" not in template
    assert "Do not edit candidate or production text" in template

    for route_id in (
        "reviewer_pro",
        "narrative_planner_pro",
        "scribe_flash",
        "scribe_pro",
    ):
        assert (
            registry["routes"][route_id]["invocation_contract"]
            == "claude_longform_governance"
        )

def test_profile_safety_validator_flags_dangerous_default_profile():
    bad_profile = {
        "modes": {
            "bad_mode": {
                "tiers": {
                    "full": {
                        "coder": {
                            "executor_type": "cli_agent",
                            "cli_command": "ccs --allow-dangerously-skip-permissions"
                        }
                    }
                }
            }
        }
    }
    findings = validate_cli_agent_profiles(bad_profile)
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert findings[0].profile == "bad_mode"
    assert findings[0].flag == "--allow-dangerously-skip-permissions"
