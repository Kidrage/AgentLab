"""Tests for forbidden tracked file checker."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Import the module under test
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_forbidden_tracked_files import (
    ALLOWED_PATTERNS,
    FORBIDDEN_PATTERNS,
    _match_any,
    main,
)


def test_match_any_direct_env() -> None:
    assert _match_any(".env", FORBIDDEN_PATTERNS) is True


def test_match_any_nested_env() -> None:
    assert _match_any("agent_runtime/.env", FORBIDDEN_PATTERNS) is True


def test_match_any_env_backup() -> None:
    assert _match_any(".env.bak", FORBIDDEN_PATTERNS) is True


def test_match_any_pem_file() -> None:
    assert _match_any("certs/server.pem", FORBIDDEN_PATTERNS) is True


def test_match_any_key_file() -> None:
    assert _match_any("secrets/api.key", FORBIDDEN_PATTERNS) is True


def test_match_any_p12_file() -> None:
    assert _match_any("certs/identity.p12", FORBIDDEN_PATTERNS) is True


def test_match_any_pfx_file() -> None:
    assert _match_any("certs/identity.pfx", FORBIDDEN_PATTERNS) is True


def test_match_any_env_example_allowed() -> None:
    """env.example files should NOT match forbidden patterns."""
    assert _match_any(".env.example", FORBIDDEN_PATTERNS) is True
    # But it should be in allowed patterns
    assert _match_any(".env.example", ALLOWED_PATTERNS) is True


def test_match_any_safe_file_not_forbidden() -> None:
    """Normal files should NOT match forbidden patterns."""
    assert _match_any("README.md", FORBIDDEN_PATTERNS) is False
    assert _match_any("src/main.py", FORBIDDEN_PATTERNS) is False


def test_allowed_patterns_exempt_env_example() -> None:
    """env.example files match forbidden but are exempted by allowed patterns."""
    assert _match_any(".env.example", FORBIDDEN_PATTERNS) is True
    assert _match_any(".env.example", ALLOWED_PATTERNS) is True


def test_no_real_secrets_tracked() -> None:
    """Integration test: run the actual checker against the repo.
    This test requires git access and will be skipped if .git is unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            pytest.skip("git ls-files failed (sandbox or no .git)")
        tracked = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        forbidden = []
        for f in tracked:
            if _match_any(f, FORBIDDEN_PATTERNS) and not _match_any(f, ALLOWED_PATTERNS):
                forbidden.append(f)
        assert forbidden == [], f"Forbidden files tracked: {forbidden}"
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"git unavailable: {exc}")
