import os
import pytest
from unittest.mock import patch
from agent_runtime.workers.auth_probe import probe_auth

def test_probe_auth_claude_code_rejects_ccs_active_file(tmp_path):
    provider_dir = tmp_path / ".claude-provider"
    provider_dir.mkdir()
    (provider_dir / "active").touch()
    
    with patch("os.path.expanduser", return_value=str(provider_dir)):
        assert probe_auth("claude_code") == "no"

def test_probe_auth_claude_code_rejects_ccs_config_file(tmp_path):
    provider_dir = tmp_path / ".claude-provider"
    provider_dir.mkdir()
    (provider_dir / "config").touch()
    
    with patch("os.path.expanduser", return_value=str(provider_dir)):
        assert probe_auth("claude_code") == "no"

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

def test_probe_auth_legacy_claude_env_does_not_certify_deepseek_binding(tmp_path):
    provider_dir = tmp_path / ".claude-provider"
    provider_dir.mkdir()
    
    with patch("os.path.expanduser", return_value=str(provider_dir)):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            assert probe_auth("claude_code") == "no"


def test_probe_auth_agy_uses_oauth_markers_not_gemini_api_key():
    with patch.dict(os.environ, {"GEMINI_API_KEY": "test-gemini-key"}, clear=True):
        with patch("os.path.exists", return_value=False):
            assert probe_auth("agy") == "unknown"

    with patch.dict(os.environ, {}, clear=True):
        with patch("os.path.exists", return_value=True):
            assert probe_auth("agy") == "yes"


def test_probe_auth_hermes_accepts_local_oauth_marker_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        with patch("os.path.exists", return_value=True):
            assert probe_auth("hermes") == "yes"
