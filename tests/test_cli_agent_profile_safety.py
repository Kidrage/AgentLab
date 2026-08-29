import pytest
import yaml
from pathlib import Path
from agent_runtime.workers.cli_command_policy import validate_cli_agent_profiles

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

def test_all_claude_code_profiles_keep_approval_required():
    from agent_runtime.workers.detector import DEFAULT_CANDIDATES

    claude = next(c for c in DEFAULT_CANDIDATES if c["worker_id"] == "claude_code")
    assert claude.get("approval_required") is True
    assert claude.get("risk_level") == "high"
    assert claude.get("default_enabled") is False

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
