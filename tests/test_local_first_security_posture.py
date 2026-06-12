from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from openclaw_local_adapter import load_openclaw_local_policy


def test_no_default_agentlab_public_api_host() -> None:
    for path in (ROOT / "config").glob("*.yml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        text = yaml.safe_dump(data)
        if "0.0.0.0" in text:
            assert path.name == "migration_profile.yml"
            assert "web_ui" in data.get("required_user_inputs", {})
            assert "public_api" not in text.lower()


def test_openclaw_adapter_security_flags_are_local_first() -> None:
    policy = load_openclaw_local_policy(ROOT)
    security = policy["security"]
    assert security["expose_agentlab_publicly"] is False
    assert security["allow_public_agentlab_api"] is False
    assert security["require_localhost_or_private_network"] is True


def test_docs_warn_not_to_expose_agentlab_publicly() -> None:
    docs = [
        ROOT / "docs" / "OPENCLAW_LOCAL_INTEGRATION.md",
        ROOT / "docs" / "WEBHOOK_INTEGRATION.md",
        ROOT / "README.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in docs)
    assert "do not expose agentlab directly to the public internet" in combined


def test_webhook_url_defaults_come_from_env_not_public_url() -> None:
    webhook_policy = yaml.safe_load((ROOT / "config" / "webhook_policy.yml").read_text(encoding="utf-8")) or {}
    for endpoint in webhook_policy.get("endpoints", []):
        assert "url" not in endpoint
        assert endpoint.get("url_env")

    local_policy = load_openclaw_local_policy(ROOT)
    feedback = local_policy["feedback"]
    assert feedback["localhost_webhook_url_env"] == "AGENTLAB_OPENCLAW_LOCAL_WEBHOOK_URL"
    assert "http://" not in yaml.safe_dump(feedback)
    assert "https://" not in yaml.safe_dump(feedback)
