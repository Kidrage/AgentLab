from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "activate_250_runtime.sh"


def test_250_runtime_activation_script_is_valid_bash() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], cwd=ROOT, check=True)


def test_250_runtime_activation_help_documents_status_only() -> None:
    result = subprocess.run(
        [str(SCRIPT), "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--status-only" in result.stdout
    assert "read-only remote activation audit" in result.stdout
    assert "No secrets are stored in this script" in result.stdout


def test_250_runtime_activation_script_does_not_embed_live_secrets() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    forbidden_patterns = [
        r"AQ\.",
        r"bbe166",
        r"ddns-gjy",
        r"CLASH_SUBSCRIBE_URL=https://",
        r"GEMINI_API_KEY=[A-Za-z0-9_.-]{12,}",
        r"GOOGLE_API_KEY=[A-Za-z0-9_.-]{12,}",
    ]
    for pattern in forbidden_patterns:
        assert not re.search(pattern, text), f"script embeds secret-like pattern: {pattern}"


def test_250_runtime_status_only_runs_before_secret_prompts() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    status_pos = text.index('if [[ "$STATUS_ONLY" == "1" ]]')
    clash_prompt_pos = text.index("Clash subscription URL:")
    gemini_prompt_pos = text.index("Gemini API key:")

    assert status_pos < clash_prompt_pos
    assert status_pos < gemini_prompt_pos
    assert "secret_key_presence" in text[status_pos:clash_prompt_pos]


def test_250_runtime_activation_hardens_remote_proxy_and_gemini_auth() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'base_env.pop("ALL_PROXY", None)' in text
    assert 'base_env.pop("all_proxy", None)' in text
    assert '"GOOGLE_GENAI_USE_GCA": "false"' in text
    assert '"GOOGLE_GENAI_USE_VERTEXAI": "false"' in text
    assert '"GEMINI_CLI_TRUST_WORKSPACE": "true"' in text
    assert '["selectedType"] = "gemini-api-key"' in text
    assert '"--skip-trust"' in text


def test_250_runtime_activation_uses_started_proxy_for_gemini_smoke() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'proxy_url = "http://127.0.0.1:8123"' in text
    assert 'urllib.request.ProxyHandler' in text
    assert 'cli_env = proxy_env.copy()' in text
    assert 'cli_env.pop("GOOGLE_API_KEY", None)' in text
    assert "timeout=120" in text


def test_250_runtime_activation_reports_smoke_timeouts_as_results() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "except subprocess.TimeoutExpired as exc:" in text
    assert "return 124, redact(output.strip())" in text


def test_250_runtime_activation_redacts_remote_command_output() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "def redact(text: str) -> str:" in text
    assert 'text.replace(sub_url, "<CLASH_SUBSCRIBE_URL>")' in text
    assert 'r"token=[A-Za-z0-9._-]+"' in text
    assert "return proc.returncode, redact(proc.stdout.strip())" in text


def test_250_runtime_status_reports_direct_mihomo_runtime() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "mihomo_direct_process" in text
    assert "proxy_8123_listening" in text
    assert "pgrep -af '/home/admin/.local/bin/mihomo -d /home/admin/.config/mihomo'" in text
    assert "ss -ltn 2>/dev/null | grep ':8123 '" in text


def test_250_runtime_activation_has_clash_user_agent_subscription_fallback() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert '"User-Agent": "clash-verge/v2.0.0"' in text
    assert '"mixed-port: 8123"' in text
    assert "mihomo_config_fallback" in text
    assert "urllib.request.ProxyHandler({})" in text
