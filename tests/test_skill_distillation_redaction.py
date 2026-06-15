from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from skill_distiller import redact_sensitive_text


def test_skill_distillation_redaction_patterns() -> None:
    private_key = "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"
    text = f"TOKEN=secret-token\nuser@example.com\n/" + "Users" + "/alice/work\n{private_key}"
    redacted = redact_sensitive_text(text)
    assert "secret-token" not in redacted
    assert "user@example.com" not in redacted
    assert "/" + "Users" + "/alice" not in redacted
    assert "BEGIN PRIVATE KEY" not in redacted
