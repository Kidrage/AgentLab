import os
import pytest
from unittest.mock import patch
from agent_runtime.workers.auth_probe import probe_auth

def test_probe_auth_claude_code_detects_ccs_active_file(tmp_path):
    provider_dir = tmp_path / ".claude-provider"
    provider_dir.mkdir()
    (provider_dir / "active").touch()
    
    with patch("os.path.expanduser", return_value=str(provider_dir)):
        assert probe_auth("claude_code") == "yes"

def test_probe_auth_claude_code_detects_ccs_config_file(tmp_path):
    provider_dir = tmp_path / ".claude-provider"
    provider_dir.mkdir()
    (provider_dir / "config").touch()
    
    with patch("os.path.expanduser", return_value=str(provider_dir)):
        assert probe_auth("claude_code") == "yes"

def test_probe_auth_claude_code_without_env_or_ccs_config_returns_no(tmp_path):
    provider_dir = tmp_path / ".claude-provider"
    provider_dir.mkdir()
    
    with patch("os.path.expanduser", return_value=str(provider_dir)):
        with patch.dict(os.environ, clear=True):
            assert probe_auth("claude_code") == "no"

def test_probe_auth_does_not_leak_home_path_or_key_values():
    with patch.dict(os.environ, clear=True):
        res = probe_auth("claude_code")
        assert "/" not in res

def test_probe_auth_legacy_claude_env_still_works(tmp_path):
    provider_dir = tmp_path / ".claude-provider"
    provider_dir.mkdir()
    
    with patch("os.path.expanduser", return_value=str(provider_dir)):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            assert probe_auth("claude_code") == "yes"
